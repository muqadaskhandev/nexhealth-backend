"""Public online booking portal (unauthenticated)."""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment_types import AppointmentTypeDef
from app.models.booking_form import BookingFieldType, BookingFormField, BookingInsurance
from app.models.location import Location
from app.models.practice import Practice
from app.models.providers import Provider, ProviderStatus
from app.models.staff import ActivityType, Appointment, AppointmentStatus, Patient
from app.schemas.public_booking import PublicBookRequest
from app.services import appointment_rules_service, appointment_types_service, staff_service
from app.services.booking_availability_service import (
    compute_openings,
    filter_types_for_patient,
    load_scheduling_data,
    practice_slug,
)


class PatientNotFoundError(Exception):
    """Returning patient could not be matched to an existing record."""


def _normalize_name(value: str) -> str:
    return value.strip().lower()


def _is_valid_number(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        float(text)
        return True
    except ValueError:
        return False


def _is_iso_date(value: object) -> bool:
    text = str(value or "").strip()
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def _is_date_question(field: BookingFormField) -> bool:
    if field.field_type == BookingFieldType.DATE:
        return True
    if field.field_type not in (BookingFieldType.NUMBER, BookingFieldType.TEXT):
        return False
    return bool(re.search(r"\b(date|when|calendar|happened|dob|birth)\b", field.label.lower()))


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[-1]


def _names_match(submitted: str, stored: str) -> bool:
    a = _normalize_name(submitted)
    b = _normalize_name(stored)
    if not a or not b:
        return False
    if a == b:
        return True
    return _levenshtein(a, b) <= 1


def _normalize_phone(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def _phones_match(submitted: str, stored: str) -> bool:
    a = _normalize_phone(submitted)
    b = _normalize_phone(stored)
    if not a or not b:
        return False
    if len(a) >= 10 and len(b) >= 10:
        return a[-10:] == b[-10:]
    return a == b


def _parse_uuid_list(raw: str | None) -> list[uuid.UUID] | None:
    if not raw:
        return None
    out: list[uuid.UUID] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        out.append(uuid.UUID(part))
    return out or None


async def resolve_practice_by_slug(db: AsyncSession, slug: str) -> Practice | None:
    result = await db.execute(select(Practice).where(Practice.is_active.is_(True)))
    for practice in result.scalars().all():
        if practice_slug(practice.name) == slug.lower():
            return practice
    return None


async def _practice_locations(db: AsyncSession, practice_id: uuid.UUID) -> list[Location]:
    result = await db.execute(select(Location).where(Location.practice_id == practice_id).order_by(Location.name))
    return list(result.scalars().all())


def _filter_locations(
    locations: list[Location],
    *,
    lid: str | None,
    location_ids: list[uuid.UUID] | None,
    practice_id: uuid.UUID,
) -> list[Location]:
    if location_ids:
        id_set = set(location_ids)
        return [loc for loc in locations if loc.id in id_set]
    if lid and not str(practice_id).startswith(lid):
        return []
    return locations


async def get_booking_info(
    db: AsyncSession,
    *,
    slug: str,
    lid: str | None = None,
    location_ids_raw: str | None = None,
) -> dict | None:
    practice = await resolve_practice_by_slug(db, slug)
    if practice is None:
        return None

    location_ids = _parse_uuid_list(location_ids_raw)
    all_locations = await _practice_locations(db, practice.id)
    locations = _filter_locations(all_locations, lid=lid, location_ids=location_ids, practice_id=practice.id)
    if not locations:
        return None

    separate = any(loc.separate_by_patient_type for loc in locations)
    payments_enabled = bool((practice.enabled_products or {}).get("payments"))
    return {
        "practice_name": practice.name,
        "practice_logo_url": practice.logo_url,
        "separate_by_patient_type": separate,
        "payments_enabled": payments_enabled,
        "booking_redirect_url": practice.booking_redirect_url or "",
        "locations": [
            {
                "id": loc.id,
                "name": loc.name,
                "address": loc.address,
                "city": loc.city,
                "state": loc.state,
                "zip_code": loc.zip_code,
                "phone": loc.phone,
                "logo_url": loc.logo_url,
                "separate_by_patient_type": loc.separate_by_patient_type,
                "ask_for_insurance": loc.ask_for_insurance,
            }
            for loc in locations
        ],
    }


async def _get_location(db: AsyncSession, practice_id: uuid.UUID, location_id: uuid.UUID) -> Location | None:
    loc = await db.get(Location, location_id)
    if loc is None or loc.practice_id != practice_id:
        return None
    return loc


async def list_booking_types(
    db: AsyncSession,
    *,
    slug: str,
    location_id: uuid.UUID,
    patient_kind: str,
    appointment_type_ids_raw: str | None = None,
    lid: str | None = None,
) -> list[AppointmentTypeDef] | None:
    practice = await resolve_practice_by_slug(db, slug)
    if practice is None:
        return None
    loc = await _get_location(db, practice.id, location_id)
    if loc is None:
        return None
    if lid and not str(practice.id).startswith(lid):
        return None

    type_ids = _parse_uuid_list(appointment_type_ids_raw)
    result = await db.execute(
        select(AppointmentTypeDef)
        .where(
            AppointmentTypeDef.practice_id == practice.id,
            AppointmentTypeDef.location_id == location_id,
        )
        .order_by(AppointmentTypeDef.name)
    )
    types = list(result.scalars().all())
    return filter_types_for_patient(types, patient_kind, type_ids)


async def list_booking_providers(
    db: AsyncSession,
    *,
    slug: str,
    location_id: uuid.UUID,
    appointment_type_id: uuid.UUID,
    provider_ids_raw: str | None = None,
    lid: str | None = None,
) -> list[Provider] | None:
    practice = await resolve_practice_by_slug(db, slug)
    if practice is None:
        return None
    loc = await _get_location(db, practice.id, location_id)
    if loc is None:
        return None
    if lid and not str(practice.id).startswith(lid):
        return None

    provider_ids = _parse_uuid_list(provider_ids_raw)
    result = await db.execute(
        select(Provider).where(
            Provider.practice_id == practice.id,
            Provider.location_id == location_id,
            Provider.status == ProviderStatus.ACTIVE,
        )
    )
    providers = [
        p
        for p in result.scalars().all()
        if str(appointment_type_id) in [str(x) for x in (p.default_appointment_type_ids or [])]
    ]
    if provider_ids:
        id_set = set(provider_ids)
        providers = [p for p in providers if p.id in id_set]
    return providers


async def list_booking_openings(
    db: AsyncSession,
    *,
    slug: str,
    location_id: uuid.UUID,
    appointment_type_id: uuid.UUID,
    provider_id: uuid.UUID | None = None,
    provider_ids_raw: str | None = None,
    days: int = 14,
    lid: str | None = None,
) -> list[dict] | None:
    practice = await resolve_practice_by_slug(db, slug)
    if practice is None:
        return None
    loc = await _get_location(db, practice.id, location_id)
    if loc is None:
        return None
    if lid and not str(practice.id).startswith(lid):
        return None

    appt_type = await db.get(AppointmentTypeDef, appointment_type_id)
    if appt_type is None or appt_type.practice_id != practice.id or appt_type.location_id != location_id:
        return None

    provider_ids = _parse_uuid_list(provider_ids_raw)
    providers, slots, blocks, appointments = await load_scheduling_data(
        db, practice_id=practice.id, location_id=location_id
    )
    if provider_ids:
        id_set = set(provider_ids)
        providers = [p for p in providers if p.id in id_set]

    return compute_openings(
        appointment_type=appt_type,
        providers=providers,
        slots=slots,
        blocks=blocks,
        appointments=appointments,
        days_needed=min(days, 30),
        provider_id=provider_id,
    )


async def list_booking_form_fields(
    db: AsyncSession,
    *,
    slug: str,
    location_id: uuid.UUID,
    patient_kind: str,
    lid: str | None = None,
) -> list[BookingFormField] | None:
    practice = await resolve_practice_by_slug(db, slug)
    if practice is None:
        return None
    loc = await _get_location(db, practice.id, location_id)
    if loc is None:
        return None
    if lid and not str(practice.id).startswith(lid):
        return None

    result = await db.execute(
        select(BookingFormField)
        .where(
            BookingFormField.practice_id == practice.id,
            BookingFormField.location_id == location_id,
        )
        .order_by(BookingFormField.position)
    )
    fields = list(result.scalars().all())
    payments_enabled = bool((practice.enabled_products or {}).get("payments"))
    visible: list[BookingFormField] = []
    for field in fields:
        if field.show_to not in ("all", patient_kind):
            continue
        if field.field_type == BookingFieldType.PAYMENT and not payments_enabled:
            continue
        visible.append(field)
    return visible


async def list_booking_insurances(
    db: AsyncSession,
    *,
    slug: str,
    location_id: uuid.UUID,
    lid: str | None = None,
) -> list[BookingInsurance] | None:
    practice = await resolve_practice_by_slug(db, slug)
    if practice is None:
        return None
    loc = await _get_location(db, practice.id, location_id)
    if loc is None:
        return None
    if lid and not str(practice.id).startswith(lid):
        return None
    if not loc.ask_for_insurance:
        return []

    result = await db.execute(
        select(BookingInsurance)
        .where(
            BookingInsurance.practice_id == practice.id,
            BookingInsurance.location_id == location_id,
        )
        .order_by(BookingInsurance.name)
    )
    return list(result.scalars().all())


async def _find_patient(
    db: AsyncSession,
    practice_id: uuid.UUID,
    location_id: uuid.UUID,
    *,
    first_name: str,
    last_name: str,
    dob: date | None,
    email: str,
    phone: str,
) -> Patient | None:
    if dob is None:
        return None
    email_norm = email.strip().lower()
    phone_norm = _normalize_phone(phone)
    if not email_norm and not phone_norm:
        return None

    result = await db.execute(
        select(Patient).where(
            Patient.practice_id == practice_id,
            Patient.location_id == location_id,
            Patient.dob == dob,
            Patient.archived.is_(False),
        )
    )
    for patient in result.scalars().all():
        if not _names_match(first_name, patient.first_name):
            continue
        if not _names_match(last_name, patient.last_name):
            continue
        contact_match = bool(email_norm and patient.email and patient.email.lower() == email_norm)
        if not contact_match and phone_norm:
            contact_match = _phones_match(phone, patient.phone or "")
        if contact_match:
            return patient
    return None


async def _slot_available(
    db: AsyncSession,
    *,
    practice_id: uuid.UUID,
    location_id: uuid.UUID,
    appointment_type: AppointmentTypeDef,
    provider: Provider,
    starts_at: datetime,
) -> bool:
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=timezone.utc)

    providers, slots, blocks, appointments = await load_scheduling_data(
        db, practice_id=practice_id, location_id=location_id
    )
    date_str = starts_at.date().isoformat()
    start_min = starts_at.hour * 60 + starts_at.minute
    today = datetime.now(timezone.utc).date()
    max_scan = (starts_at.date() - today).days + 1
    if max_scan < 1:
        return False

    openings = compute_openings(
        appointment_type=appointment_type,
        providers=[provider],
        slots=slots,
        blocks=blocks,
        appointments=appointments,
        days_needed=max_scan,
        max_scan=max_scan,
        provider_id=provider.id,
    )
    for day in openings:
        if day["date"] != date_str:
            continue
        for slot in day["times"]:
            if slot["provider_id"] == str(provider.id) and slot["minutes"] == start_min:
                return True
    return False


async def book_appointment(
    db: AsyncSession,
    *,
    slug: str,
    payload: PublicBookRequest,
    lid: str | None = None,
) -> dict | None:
    practice = await resolve_practice_by_slug(db, slug)
    if practice is None:
        return None
    loc = await _get_location(db, practice.id, payload.location_id)
    if loc is None:
        return None
    if lid and not str(practice.id).startswith(lid):
        return None

    appt_type = await db.get(AppointmentTypeDef, payload.appointment_type_id)
    if appt_type is None or appt_type.practice_id != practice.id or appt_type.location_id != payload.location_id:
        raise ValueError("Appointment type not found")
    if not appt_type.available_online:
        raise ValueError("This appointment type is not available for online booking")

    provider = await db.get(Provider, payload.provider_id)
    if provider is None or provider.practice_id != practice.id or provider.location_id != payload.location_id:
        raise ValueError("Provider not found")
    if provider.status != ProviderStatus.ACTIVE:
        raise ValueError("Provider is not available")
    if str(appt_type.id) not in [str(x) for x in (provider.default_appointment_type_ids or [])]:
        raise ValueError("Provider does not offer this appointment type")

    filtered = filter_types_for_patient([appt_type], payload.patient_kind)
    if not filtered:
        raise ValueError("This appointment type is not available for this patient type")

    if not await _slot_available(
        db,
        practice_id=practice.id,
        location_id=payload.location_id,
        appointment_type=appt_type,
        provider=provider,
        starts_at=payload.starts_at,
    ):
        raise ValueError("That time slot is no longer available — please choose another time")

    if payload.patient_kind == "new":
        if not payload.dob:
            raise ValueError("Date of birth is required for new patients")
        if not payload.phone.strip():
            raise ValueError("Phone number is required")
        if not payload.zip_code.strip():
            raise ValueError("Zip code is required")
        if not payload.gender.strip():
            raise ValueError("Legal sex is required")

    insurance_name: str | None = None
    if loc.ask_for_insurance:
        insurances = await list_booking_insurances(
            db, slug=slug, location_id=payload.location_id, lid=lid
        )
        if insurances:
            if payload.insurance_id is None:
                raise ValueError("Please select your insurance")
            selected = next((i for i in insurances if i.id == payload.insurance_id), None)
            if selected is None:
                raise ValueError("Please select a valid insurance")
            insurance_name = selected.name

    form_fields = await list_booking_form_fields(
        db, slug=slug, location_id=payload.location_id, patient_kind=payload.patient_kind, lid=lid
    )
    for field in form_fields:
        if field.field_type == BookingFieldType.NOTE:
            continue
        answer = payload.form_answers.get(str(field.id))
        if not field.required:
            continue
        if field.field_type == BookingFieldType.MULTI_SELECT:
            if not isinstance(answer, list) or len(answer) == 0:
                raise ValueError(f"Please complete: {field.label}")
            continue
        if field.field_type == BookingFieldType.PAYMENT:
            if not isinstance(answer, dict) or not answer.get("authorized"):
                raise ValueError(f"Please complete: {field.label}")
            continue
        if _is_date_question(field):
            if not _is_iso_date(answer):
                raise ValueError(f"Please pick a date for: {field.label}")
            continue
        if field.field_type == BookingFieldType.NUMBER:
            if not _is_valid_number(answer):
                raise ValueError(f"Please enter a valid number for: {field.label}")
            continue
        if not str(answer or "").strip():
            raise ValueError(f"Please complete: {field.label}")

    from app.services.field_validation_service import validate_booking_patient_fields

    cleaned = validate_booking_patient_fields(
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=str(payload.email or ""),
        phone=payload.phone,
        zip_code=payload.zip_code,
        patient_kind=payload.patient_kind,
        booking_for=payload.booking_for,
        guarantor_first_name=payload.guarantor_first_name,
        guarantor_last_name=payload.guarantor_last_name,
        guarantor_email=str(payload.guarantor_email or ""),
        guarantor_phone=payload.guarantor_phone,
        form_answers=payload.form_answers,
        form_fields=form_fields,
    )

    if payload.patient_kind == "existing":
        if not payload.dob:
            raise ValueError("Date of birth is required for returning patients")
        if not str(payload.email).strip() and not payload.phone.strip():
            raise ValueError("Email or phone is required to find your patient record")
        patient = await _find_patient(
            db,
            practice.id,
            payload.location_id,
            first_name=cleaned["first_name"],
            last_name=cleaned["last_name"],
            dob=payload.dob,
            email=cleaned["email"],
            phone=cleaned["phone"],
        )
        if patient is None:
            raise PatientNotFoundError()
    else:
        patient = Patient(
            practice_id=practice.id,
            location_id=payload.location_id,
            first_name=cleaned["first_name"],
            last_name=cleaned["last_name"],
            dob=payload.dob,
            gender=payload.gender.strip(),
            email=cleaned["email"],
            phone=cleaned["phone"],
            address=cleaned["zip_code"],
            synced=False,
            insurance_data=(
                {"status": "unverified", "name": insurance_name, "source": "online_booking"}
                if insurance_name
                else {"status": "unknown", "name": "Unknown"}
            ),
            notification_prefs=(
                {"call_text_consent": True, "email": True, "sms": True}
                if payload.call_text_consent
                else {}
            ),
        )
        db.add(patient)
        await db.flush()
        await staff_service._log_activity(  # noqa: SLF001
            db,
            patient_id=patient.id,
            activity_type=ActivityType.NOTE,
            title="Patient record created via online booking",
        )

    if payload.patient_kind == "existing":
        if payload.gender.strip():
            patient.gender = payload.gender.strip()
        if payload.zip_code.strip():
            patient.address = payload.zip_code.strip()
        if insurance_name:
            patient.insurance_data = {
                **(patient.insurance_data or {}),
                "status": "unverified",
                "name": insurance_name,
                "source": "online_booking",
            }
        if payload.call_text_consent:
            patient.notification_prefs = {
                **(patient.notification_prefs or {}),
                "call_text_consent": True,
                "email": True,
                "sms": True,
            }

    await appointment_types_service._attach_rules(db, [appt_type])  # noqa: SLF001
    insertion_rules = getattr(appt_type, "insertion_rules", [])
    booking_extra: dict = {
        "provider_id": str(provider.id),
        "form_answers": payload.form_answers,
    }
    if insurance_name:
        booking_extra["insurance_name"] = insurance_name
        if payload.insurance_id:
            booking_extra["insurance_id"] = str(payload.insurance_id)
    if payload.call_text_consent:
        booking_extra["call_text_consent"] = True
    if payload.utm_source:
        booking_extra["utm_source"] = payload.utm_source
    if payload.utm_medium:
        booking_extra["utm_medium"] = payload.utm_medium
    if payload.utm_campaign:
        booking_extra["utm_campaign"] = payload.utm_campaign
    if payload.booking_for != "self":
        booking_extra["booking_for"] = payload.booking_for
        booking_extra["guarantor"] = {
            "first_name": cleaned["guarantor_first_name"],
            "last_name": cleaned["guarantor_last_name"],
            "email": cleaned["guarantor_email"],
            "phone": cleaned["guarantor_phone"],
        }

    meta = appointment_rules_service.build_appointment_meta(
        source="online_booking",
        insertion_rules=insertion_rules,
        extra=booking_extra,
    )

    appt = Appointment(
        practice_id=practice.id,
        location_id=payload.location_id,
        patient_id=patient.id,
        provider_name=provider.name,
        appointment_type=appt_type.name,
        appointment_type_def_id=appt_type.id,
        starts_at=payload.starts_at if payload.starts_at.tzinfo else payload.starts_at.replace(tzinfo=timezone.utc),
        duration_minutes=appt_type.duration_minutes,
        status=AppointmentStatus.UNCONFIRMED,
        meta=meta,
    )
    db.add(appt)
    await db.flush()

    await staff_service._log_activity(  # noqa: SLF001
        db,
        patient_id=patient.id,
        activity_type=ActivityType.APPOINTMENT,
        title=f"Online appointment booked — {appt_type.name}",
        meta={"appointment_id": str(appt.id), **meta},
    )

    await staff_service.evaluate_automatic_form_requests(
        db,
        practice_id=practice.id,
        location_id=payload.location_id,
        appointment=appt,
    )

    if insurance_name:
        await staff_service._log_activity(  # noqa: SLF001
            db,
            patient_id=patient.id,
            activity_type=ActivityType.NOTE,
            title=f"Insurance selected during online booking — {insurance_name}",
            meta={"insurance_name": insurance_name, "source": "online_booking"},
        )

    when = appt.starts_at.astimezone(timezone.utc).strftime("%A, %B %d at %I:%M %p")
    return {
        "message": "Your appointment has been booked",
        "appointment_id": appt.id,
        "confirmation": f"{appt_type.name} with {provider.name} on {when}",
        "email_sent": False,
        "email": patient.email or "",
    }
