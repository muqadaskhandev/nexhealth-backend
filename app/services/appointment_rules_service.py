"""Resolve appointment types via mapping rules and apply insertion rules (no EHR)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment_types import AppointmentTypeDef, InsertionRule, MappingRule
from app.services import appointment_types_service


@dataclass
class MappingContext:
    provider_name: str = ""
    operatory: str = ""
    visit_type: str = ""
    service_type: str = ""
    procedure_codes: list[str] = field(default_factory=list)


def _norm(value: str) -> str:
    return value.strip().lower()


def _condition_matches(condition: dict[str, Any], context: MappingContext) -> bool:
    field_name = condition.get("field", "")
    values = [_norm(v) for v in condition.get("values", []) if str(v).strip()]
    if not values:
        return False

    if field_name == "provider":
        actual = _norm(context.provider_name)
        return actual in values
    if field_name == "operatory":
        actual = _norm(context.operatory)
        return actual in values
    if field_name == "visit_type":
        actual = _norm(context.visit_type)
        return actual in values
    if field_name == "service_type":
        actual = _norm(context.service_type)
        return actual in values
    if field_name == "procedure_code":
        codes = {_norm(c) for c in context.procedure_codes if str(c).strip()}
        return bool(codes & set(values))
    return False


def rule_matches(rule: MappingRule, context: MappingContext) -> bool:
    if not rule.conditions:
        return False
    return all(_condition_matches(c, context) for c in rule.conditions)


async def evaluate_mapping_rules(
    db: AsyncSession,
    *,
    practice_id: uuid.UUID,
    location_id: uuid.UUID,
    context: MappingContext,
) -> MappingRule | None:
    result = await db.execute(
        select(MappingRule)
        .where(MappingRule.practice_id == practice_id, MappingRule.location_id == location_id)
        .order_by(MappingRule.position)
    )
    for rule in result.scalars().all():
        if rule_matches(rule, context):
            return rule
    return None


async def get_appointment_type_by_id(
    db: AsyncSession,
    *,
    practice_id: uuid.UUID,
    location_id: uuid.UUID,
    appointment_type_id: uuid.UUID,
) -> AppointmentTypeDef | None:
    at = await db.get(AppointmentTypeDef, appointment_type_id)
    if at is None or at.practice_id != practice_id or at.location_id != location_id:
        return None
    await appointment_types_service._attach_rules(db, [at])  # noqa: SLF001
    return at


async def get_appointment_type_by_name(
    db: AsyncSession,
    *,
    practice_id: uuid.UUID,
    location_id: uuid.UUID,
    name: str,
) -> AppointmentTypeDef | None:
    result = await db.execute(
        select(AppointmentTypeDef).where(
            AppointmentTypeDef.practice_id == practice_id,
            AppointmentTypeDef.location_id == location_id,
            AppointmentTypeDef.name == name,
        )
    )
    at = result.scalar_one_or_none()
    if at is None:
        return None
    await appointment_types_service._attach_rules(db, [at])  # noqa: SLF001
    return at


def insertion_rules_payload(rules: list[InsertionRule]) -> list[dict[str, Any]]:
    return [{"code_type": r.code_type, "codes": r.codes} for r in rules]


def build_appointment_meta(
    *,
    source: str,
    insertion_rules: list[InsertionRule] | None = None,
    mapping_rule_id: uuid.UUID | None = None,
    mapping_context: MappingContext | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {"source": source}
    if insertion_rules:
        meta["insertion_rules"] = insertion_rules_payload(insertion_rules)
    if mapping_rule_id is not None:
        meta["mapping_rule_id"] = str(mapping_rule_id)
    if mapping_context is not None:
        meta["mapping_context"] = {
            "provider_name": mapping_context.provider_name,
            "operatory": mapping_context.operatory,
            "visit_type": mapping_context.visit_type,
            "service_type": mapping_context.service_type,
            "procedure_codes": mapping_context.procedure_codes,
        }
    if extra:
        meta.update(extra)
    return meta


async def resolve_appointment_type(
    db: AsyncSession,
    *,
    practice_id: uuid.UUID,
    location_id: uuid.UUID,
    appointment_type_id: uuid.UUID | None = None,
    appointment_type_name: str | None = None,
    mapping_context: MappingContext | None = None,
    source: str = "staff",
) -> tuple[AppointmentTypeDef | None, dict[str, Any]]:
    """Pick NexHealth appointment type + build meta (insertion rules, mapping info)."""
    matched_rule: MappingRule | None = None
    appt_type: AppointmentTypeDef | None = None

    if appointment_type_id is not None:
        appt_type = await get_appointment_type_by_id(
            db, practice_id=practice_id, location_id=location_id, appointment_type_id=appointment_type_id
        )
    elif appointment_type_name:
        appt_type = await get_appointment_type_by_name(
            db, practice_id=practice_id, location_id=location_id, name=appointment_type_name
        )

    if appt_type is None and mapping_context is not None:
        matched_rule = await evaluate_mapping_rules(
            db, practice_id=practice_id, location_id=location_id, context=mapping_context
        )
        if matched_rule is not None:
            appt_type = await get_appointment_type_by_id(
                db,
                practice_id=practice_id,
                location_id=location_id,
                appointment_type_id=matched_rule.target_appointment_type_id,
            )

    insertion_rules = list(getattr(appt_type, "insertion_rules", []) or []) if appt_type else []
    meta = build_appointment_meta(
        source=source,
        insertion_rules=insertion_rules,
        mapping_rule_id=matched_rule.id if matched_rule else None,
        mapping_context=mapping_context,
    )
    return appt_type, meta


async def retag_appointments_at_location(
    db: AsyncSession,
    *,
    practice_id: uuid.UUID,
    location_id: uuid.UUID,
    limit: int = 500,
) -> int:
    """Re-evaluate mapping rules for appointments that have mapping_context stored."""
    from app.models.staff import Appointment

    result = await db.execute(
        select(Appointment)
        .where(
            Appointment.practice_id == practice_id,
            Appointment.location_id == location_id,
            Appointment.meta.isnot(None),
        )
        .order_by(Appointment.starts_at.desc())
        .limit(limit)
    )
    updated = 0
    for appt in result.scalars().all():
        raw = appt.meta or {}
        ctx_raw = raw.get("mapping_context")
        if not isinstance(ctx_raw, dict):
            continue
        context = MappingContext(
            provider_name=str(ctx_raw.get("provider_name", appt.provider_name)),
            operatory=str(ctx_raw.get("operatory", "")),
            visit_type=str(ctx_raw.get("visit_type", "")),
            service_type=str(ctx_raw.get("service_type", "")),
            procedure_codes=[str(c) for c in ctx_raw.get("procedure_codes", [])],
        )
        matched_rule = await evaluate_mapping_rules(
            db, practice_id=practice_id, location_id=location_id, context=context
        )
        if matched_rule is None:
            continue
        appt_type = await get_appointment_type_by_id(
            db,
            practice_id=practice_id,
            location_id=location_id,
            appointment_type_id=matched_rule.target_appointment_type_id,
        )
        if appt_type is None:
            continue
        appt.appointment_type_def_id = appt_type.id
        appt.appointment_type = appt_type.name
        insertion_rules = list(getattr(appt_type, "insertion_rules", []) or [])
        appt.meta = {
            **raw,
            **build_appointment_meta(
                source=str(raw.get("source", "retag")),
                insertion_rules=insertion_rules,
                mapping_rule_id=matched_rule.id,
                mapping_context=context,
            ),
        }
        updated += 1
    if updated:
        await db.flush()
    return updated
