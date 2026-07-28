"""Rules for how NexHealth groups reminder and other template messages.

Implements help-center behavior:
- Reminder consolidation only when INSERTCONFIRMAPPT or APPOINTMENT_REGISTRATION
  (APPOINTMENTREGISTRATION) appears in reminder content.
- Shared phone (family messaging off): separate reminders per appointment;
  confirm/cancel replies still apply to all appointments reminded on that number.
- Family messaging on: same-day guarantor reminders are grouped with patient names.
- Single patient: appointments within 30 minutes (end→start) group; only the first
  is listed in details. Appointment journeys require the same journey key.
- Other templates: at most one send per phone + patient name within 6 hours;
  messages are not merged, but INSERTCONFIRMAPPT replies apply to all mentioned appts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

CONSOLIDATION_TOKENS = (
    "INSERTCONFIRMAPPT",
    "APPOINTMENT_REGISTRATION",
    "APPOINTMENTREGISTRATION",
    "CONFIRM_APPOINTMENT",
)

TOKEN_PATTERN = re.compile(
    r"\{\{\s*(" + "|".join(CONSOLIDATION_TOKENS) + r")\s*\}\}"
    r"|"
    r"\b(" + "|".join(CONSOLIDATION_TOKENS) + r")\b",
    re.IGNORECASE,
)

SAME_DAY_GAP = timedelta(minutes=30)
OTHER_TEMPLATE_DEDUPE_WINDOW = timedelta(hours=6)


def reminder_supports_consolidation(content: str | None) -> bool:
    """True when reminder copy includes a consolidating confirm smart command."""
    if not content:
        return False
    return bool(TOKEN_PATTERN.search(content))


def normalize_phone(phone: str | None) -> str:
    return re.sub(r"\D", "", phone or "")


@dataclass(frozen=True)
class ReminderAppointment:
    id: UUID | str
    patient_id: UUID | str
    patient_name: str
    patient_phone: str
    starts_at: datetime
    duration_minutes: int = 30
    appointment_type: str = ""
    journey_key: str | None = None  # appointment-type / journey id when using journeys
    guarantor_phone: str | None = None

    @property
    def ends_at(self) -> datetime:
        return self.starts_at + timedelta(minutes=self.duration_minutes)

    @property
    def routing_phone(self) -> str:
        return normalize_phone(self.guarantor_phone) or normalize_phone(self.patient_phone)


@dataclass
class MessageGroup:
    mode: Literal[
        "shared_phone_separate",
        "family_same_day",
        "single_patient_cluster",
        "single",
        "unconsolidated",
    ]
    recipient_phone: str
    recipient_label: str
    appointment_ids: list[str] = field(default_factory=list)
    listed_appointment_ids: list[str] = field(default_factory=list)
    patient_names: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    confirm_applies_to_all: bool = True


def _sort_key(a: ReminderAppointment) -> datetime:
    return a.starts_at


def _same_calendar_day(a: datetime, b: datetime) -> bool:
    return a.date() == b.date()


def _cluster_single_patient(
    appts: list[ReminderAppointment],
    *,
    journeys_enabled: bool,
) -> list[list[ReminderAppointment]]:
    """Group one patient's same-day appts when gap end→start is under 30 minutes."""
    if not appts:
        return []
    ordered = sorted(appts, key=_sort_key)
    clusters: list[list[ReminderAppointment]] = [[ordered[0]]]
    for appt in ordered[1:]:
        prev = clusters[-1][-1]
        same_journey = (
            not journeys_enabled
            or (prev.journey_key and prev.journey_key == appt.journey_key)
            or (prev.journey_key is None and appt.journey_key is None)
        )
        gap_ok = appt.starts_at - prev.ends_at < SAME_DAY_GAP
        if _same_calendar_day(prev.starts_at, appt.starts_at) and gap_ok and same_journey:
            clusters[-1].append(appt)
        else:
            clusters.append([appt])
    return clusters


def group_reminder_appointments(
    appointments: list[ReminderAppointment],
    *,
    template_content: str,
    family_messaging_enabled: bool,
    use_family_messaging_for_reminders: bool,
    appointment_journeys_enabled: bool = False,
) -> list[MessageGroup]:
    """Apply reminder grouping rules and return outbound message groups."""
    if not appointments:
        return []

    consolidates = reminder_supports_consolidation(template_content)
    groups: list[MessageGroup] = []

    if not consolidates:
        for appt in sorted(appointments, key=_sort_key):
            groups.append(
                MessageGroup(
                    mode="unconsolidated",
                    recipient_phone=normalize_phone(appt.patient_phone),
                    recipient_label=appt.patient_name,
                    appointment_ids=[str(appt.id)],
                    listed_appointment_ids=[str(appt.id)],
                    patient_names=[appt.patient_name],
                    notes=[
                        "Reminders are only consolidated when INSERTCONFIRMAPPT or "
                        "APPOINTMENT_REGISTRATION is used in the reminder content."
                    ],
                    confirm_applies_to_all=False,
                )
            )
        return groups

    family_on = family_messaging_enabled and use_family_messaging_for_reminders

    if family_on:
        # Group by guarantor/routing phone + calendar day
        buckets: dict[tuple[str, object], list[ReminderAppointment]] = {}
        for appt in appointments:
            phone = appt.routing_phone or normalize_phone(appt.patient_phone)
            key = (phone, appt.starts_at.date())
            buckets.setdefault(key, []).append(appt)

        for (phone, _day), bucket in sorted(buckets.items(), key=lambda x: min(a.starts_at for a in x[1])):
            ordered = sorted(bucket, key=_sort_key)
            names = []
            for a in ordered:
                if a.patient_name not in names:
                    names.append(a.patient_name)
            groups.append(
                MessageGroup(
                    mode="family_same_day",
                    recipient_phone=phone,
                    recipient_label=f"Guarantor / head of household ({phone or 'no phone'})",
                    appointment_ids=[str(a.id) for a in ordered],
                    listed_appointment_ids=[str(a.id) for a in ordered],
                    patient_names=names,
                    notes=[
                        "Family messaging sends to the guarantor and lists all same-day "
                        "appointments associated with that guarantor, including each patient's name.",
                        "A confirm or cancel reply applies to all appointments in the reminder.",
                    ],
                    confirm_applies_to_all=True,
                )
            )
        return groups

    # Shared phone / default: each appointment gets its own reminder detail grouping
    # is per-patient with the 30-minute rule.
    by_patient: dict[str, list[ReminderAppointment]] = {}
    for appt in appointments:
        by_patient.setdefault(str(appt.patient_id), []).append(appt)

    for _pid, patient_appts in by_patient.items():
        for cluster in _cluster_single_patient(
            patient_appts, journeys_enabled=appointment_journeys_enabled
        ):
            first = cluster[0]
            phone = normalize_phone(first.patient_phone)
            if len(cluster) == 1:
                note = (
                    "If patients share the same phone number, each appointment gets its own "
                    "reminder (unless family messaging is turned on)."
                )
                if appointment_journeys_enabled and first.journey_key:
                    note += " Appointment-journey grouping only applies within the same journey."
                groups.append(
                    MessageGroup(
                        mode="single",
                        recipient_phone=phone,
                        recipient_label=first.patient_name,
                        appointment_ids=[str(first.id)],
                        listed_appointment_ids=[str(first.id)],
                        patient_names=[first.patient_name],
                        notes=[note],
                        confirm_applies_to_all=True,
                    )
                )
            else:
                notes = [
                    "Appointments less than 30 minutes apart (end of first to start of next) "
                    "are grouped; only the first appointment is mentioned in the reminder details.",
                    "A confirm or cancel reply applies to all appointments in the group.",
                ]
                if appointment_journeys_enabled:
                    notes.append(
                        "With appointment journeys, this logic only applies when appointments "
                        "are part of the same appointment journey."
                    )
                # Detect skipped neighbors that were too far apart — already separate clusters
                groups.append(
                    MessageGroup(
                        mode="single_patient_cluster",
                        recipient_phone=phone,
                        recipient_label=first.patient_name,
                        appointment_ids=[str(a.id) for a in cluster],
                        listed_appointment_ids=[str(first.id)],
                        patient_names=[first.patient_name],
                        notes=notes,
                        confirm_applies_to_all=True,
                    )
                )

    # Shared-phone confirmation note: if multiple groups share a phone, replies apply to all
    by_phone: dict[str, list[MessageGroup]] = {}
    for g in groups:
        if g.recipient_phone:
            by_phone.setdefault(g.recipient_phone, []).append(g)
    for phone, phone_groups in by_phone.items():
        if len(phone_groups) > 1:
            for g in phone_groups:
                g.notes.append(
                    "Multiple reminders to the same phone number: a confirm or cancel reply "
                    "applies to all appointments they were reminded about on that number."
                )
                g.mode = "shared_phone_separate" if g.mode == "single" else g.mode

    groups.sort(key=lambda g: g.recipient_label)
    return groups


@dataclass
class OtherTemplateSendDecision:
    should_send: bool
    reason: str
    confirm_applies_to_all_mentioned: bool


def other_template_send_decision(
    *,
    template_slug: str,
    content: str,
    phone: str,
    patient_name: str,
    now: datetime,
    last_sent_at: datetime | None,
    mentioned_appointment_count: int = 1,
) -> OtherTemplateSendDecision:
    """Dedup non-reminder templates within a 6-hour window per phone + patient name."""
    if template_slug == "reminders":
        return OtherTemplateSendDecision(
            should_send=True,
            reason="Reminders use reminder-specific grouping rules.",
            confirm_applies_to_all_mentioned=reminder_supports_consolidation(content),
        )

    phone_key = normalize_phone(phone)
    name_key = (patient_name or "").strip().lower()
    has_confirm = reminder_supports_consolidation(content)

    if last_sent_at is not None and phone_key and name_key:
        if now - last_sent_at < OTHER_TEMPLATE_DEDUPE_WINDOW:
            return OtherTemplateSendDecision(
                should_send=False,
                reason=(
                    "All other templates (such as Save The Date or New Patient) only send once "
                    "to the same phone number and patient name within a 6-hour window."
                ),
                confirm_applies_to_all_mentioned=has_confirm and mentioned_appointment_count > 1,
            )

    reason = (
        "Eligible to send. Multiple eligible messages to the same number are not grouped "
        "into a single message."
    )
    if has_confirm and mentioned_appointment_count > 1:
        reason += (
            " Because the message includes INSERTCONFIRMAPPT, any reply applies to all "
            "mentioned appointments."
        )

    return OtherTemplateSendDecision(
        should_send=True,
        reason=reason,
        confirm_applies_to_all_mentioned=has_confirm and mentioned_appointment_count > 1,
    )


MESSAGE_GROUPING_RULES_DOC = {
    "title": "How does NexHealth group messages to patients?",
    "summary": (
        "When multiple reminders are sent to the same phone number NexHealth will group "
        "the appointment details."
    ),
    "consolidation_gate": (
        "We only consolidate reminders when the INSERTCONFIRMAPPT or APPOINTMENTREGISTRATION "
        "smart commands are used in the reminder content."
    ),
    "sections": [
        {
            "id": "shared_phone",
            "title": "Grouping by shared phone number",
            "items": [
                {
                    "title": "Grouping of appointment details",
                    "body": (
                        "If patients share the same phone number, each appointment will get its "
                        "own reminder. This changes if family messaging is turned on."
                    ),
                },
                {
                    "title": "Grouping of patient confirmations and cancellations",
                    "body": (
                        "If patients get multiple reminders to the same phone number and reply "
                        "(confirm or cancel), that reply will apply to all the appointments they "
                        "were reminded about."
                    ),
                },
            ],
        },
        {
            "id": "family",
            "title": "Grouping by families with Family messaging",
            "intro": (
                "Family messaging is a setting that, if enabled, sends messages to a patient's "
                "guarantor."
            ),
            "items": [
                {
                    "title": "Grouping of appointment details",
                    "body": (
                        "If the guarantor gets multiple reminders for appointments on the same "
                        "day, the reminders will be grouped and will list all appointments for "
                        "that day associated with the guarantor, including each patient's name."
                    ),
                },
                {
                    "title": "Grouping of patient confirmations and cancellations",
                    "body": (
                        "A response to confirm or cancel will apply to all of the appointments "
                        "included in the reminder."
                    ),
                },
            ],
        },
        {
            "id": "single_patient",
            "title": "Grouping multiple appointments for a single patient",
            "intro": (
                "If a patient has multiple appointments on the same day, we will group them "
                "using the following logic."
            ),
            "items": [
                {
                    "title": "Grouping of appointment details",
                    "body": (
                        "If the appointments are less than 30 minutes apart (from the end of the "
                        "first appointment to the beginning of the next) we will only mention "
                        "the first appointment in the reminder."
                    ),
                    "callout": (
                        "If a patient has multiple appointments that are not within 30 minutes "
                        "they will be treated as separate appointments and the reminders will "
                        "not be grouped."
                    ),
                },
                {
                    "title": "Grouping of patient confirmations and cancellations",
                    "body": "A response to confirm or cancel will apply to all of the appointments.",
                    "callout": (
                        "When using appointment journeys this logic will only apply if the "
                        "appointments are part of the same appointment journey."
                    ),
                    "example": (
                        "In the example below a patient would receive separate reminders for a "
                        "consultation and a periodontal appointment, but would receive a grouped "
                        "reminder for a periodontal and hygiene appointment."
                    ),
                },
            ],
        },
        {
            "id": "other_templates",
            "title": "Impact on Other Templates",
            "items": [
                {
                    "title": "All other templates",
                    "body": (
                        "All other templates (such as Save The Date or New Patient) will only "
                        "send once to the same phone number and patient name within a 6-hour "
                        "window. If multiple messages are eligible to send to the same number, "
                        "they won't be grouped into a single message. However, if the message "
                        "includes INSERTCONFIRMAPPT, any reply from the patient will apply to "
                        "all mentioned appointments."
                    ),
                },
            ],
        },
    ],
}
