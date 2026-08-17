"""LLM integration for conversational intake — Azure OpenAI or OpenAI, constrained JSON per turn."""
from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import urljoin

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

EMERGENCY_PATTERNS = re.compile(
    r"\b(chest pain|can't breathe|cannot breathe|heart attack|stroke|suicid|kill myself|"
    r"severe bleeding|unconscious|911|emergency room)\b",
    re.I,
)

HARD_RULES = """
You are a clinic intake assistant named {assistant_name}. You ONLY collect information for the current intake form.

HARD RULES (never break these):
1. Only discuss the CURRENT intake field provided in context.
2. Never provide medical advice, diagnoses, or treatment recommendations.
3. Never diagnose any condition.
4. Never collect or ask about fields not listed in allowed_fields.
5. If the patient asks a medical question, redirect them to contact their clinic or provider.
6. If the patient describes a medical emergency, set validation_status to "emergency" and stop intake.
7. Do not invent questions or fields.
8. Keep replies short, friendly, and plain language.
9. Return ONLY valid JSON matching the schema — no markdown.
10. Introduce yourself as {assistant_name} when greeting; otherwise stay focused on intake.
11. Do not mention field ids, catalog ids, or internal hashes in what the patient sees.

ANSWER VALIDATION (you must do this yourself every turn — do not accept an answer just because it has letters):
- Judge the patient's message against THIS field's type, label, and options.
- Accept only values a real patient would reasonably give for that field.
- Reject keyboard mash, random letter strings, placeholders (test, asdf, foo, xxx), fake/gibberish text, and punctuation nonsense.
- Names (first, last, full, signature): must look like a real human name (e.g. Jane, Mary Alice, O'Brien, Aqsa). Strings like "ruyelryrale" or "fhkhkfhwolffhworfro" are invalid.
- Date of birth: must be a real calendar date in the past (not today, not the future, not older than 120 years). Example: 03/15/1990.
- Insurance: must look like a real carrier, plan, or "none"/"self-pay". Strings like "hjhlu e;" are invalid.
- Address: must look like a real street address (street + city or similar), not mash.
- Notes/textarea: must be readable English (or the patient's language), not mash. Empty is OK only if the field is optional.
- Language: a real language name (English, Spanish, etc.).
- If options are listed, the answer must match one (or an obvious synonym like y → Yes).
- If invalid: validation_status must be "invalid", parsed_value must be null, and assistant_message must politely ask them to try again and say what you need. Stay on this field.
- If valid: validation_status "valid" and parsed_value is the cleaned value only (no commentary).
- If unclear: validation_status "needs_clarification" and ask a short follow-up. parsed_value null.

Your job each turn:
- Ask or confirm the current field naturally (use field label and type).
- Validate the patient's message for that field only.
- If they go off-topic medically, set validation_status to "off_topic".
"""

RESPONSE_SCHEMA = {
    "assistant_message": "string — what to show the patient",
    "field_id": "string — current field id",
    "parsed_value": "any — extracted value for the field, or null if not yet valid",
    "validation_status": "valid | invalid | needs_clarification | off_topic | emergency",
    "validation_message": "string — internal note, not shown if empty",
    "done": "boolean — true only when ALL required fields in allowed_fields are answered",
}


def detect_emergency(text: str) -> bool:
    return bool(EMERGENCY_PATTERNS.search(text))


def azure_configured() -> bool:
    return bool(settings.agent_enabled and settings.o3_access_token and settings.o3_base_uri)


def openai_configured() -> bool:
    return bool(
        settings.agent_enabled
        and (azure_configured() or settings.openai_api_key)
    )


def assistant_name() -> str:
    return (settings.ai_assistant_name or "Angelina").strip() or "Angelina"


def _azure_chat_url() -> str:
    base = settings.o3_base_uri.rstrip("/") + "/"
    url = urljoin(base, "chat/completions")
    version = settings.azure_openai_api_version
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}api-version={version}"


def _is_o_series_deployment() -> bool:
    uri = (settings.o3_base_uri or "").lower()
    model = (settings.openai_model or "").lower()
    return "o3" in uri or "o1" in uri or model.startswith("o3") or model.startswith("o1")


async def process_turn(
    *,
    patient_name: str,
    practice_name: str,
    current_field: dict,
    allowed_fields: list[dict],
    draft_answers: dict[str, Any],
    patient_message: str,
    conversation_snippet: list[dict[str, str]],
) -> dict[str, Any]:
    """Call Azure OpenAI / OpenAI (or fallback) and return structured turn result."""
    if detect_emergency(patient_message):
        return {
            "assistant_message": (
                "If this is a medical emergency, please call 911 or go to the nearest emergency room immediately. "
                "We have paused your intake. Please contact the clinic directly for urgent concerns."
            ),
            "field_id": current_field.get("id"),
            "parsed_value": None,
            "validation_status": "emergency",
            "validation_message": "Emergency keywords detected",
            "done": False,
        }

    if not openai_configured():
        return _scripted_turn(current_field, patient_message, allowed_fields, draft_answers)

    try:
        return await _llm_turn(
            patient_name=patient_name,
            practice_name=practice_name,
            current_field=current_field,
            allowed_fields=allowed_fields,
            draft_answers=draft_answers,
            patient_message=patient_message,
            conversation_snippet=conversation_snippet,
        )
    except Exception:
        logger.exception("Agent LLM call failed — falling back to scripted mode")
        return _scripted_turn(current_field, patient_message, allowed_fields, draft_answers)


async def _llm_turn(
    *,
    patient_name: str,
    practice_name: str,
    current_field: dict,
    allowed_fields: list[dict],
    draft_answers: dict[str, Any],
    patient_message: str,
    conversation_snippet: list[dict[str, str]],
) -> dict[str, Any]:
    from app.services.field_validation_service import validate_field_value

    name = assistant_name()
    field_for_model = {
        "id": current_field.get("id"),
        "label": current_field.get("label"),
        "type": current_field.get("type"),
        "required": bool(current_field.get("required")),
        "options": current_field.get("options") or [],
        "placeholder": current_field.get("placeholder") or "",
    }
    field_summary = [
        {
            "id": f.get("id"),
            "label": f.get("label"),
            "type": f.get("type"),
            "required": f.get("required", False),
            "options": f.get("options") or [],
        }
        for f in allowed_fields
    ]

    system = (
        HARD_RULES.format(assistant_name=name)
        + f"\n\nPractice: {practice_name}"
        + f"\nPatient first name (for greeting only): {patient_name.split()[0] if patient_name else 'there'}"
        + f"\n\nValidate this field now: {json.dumps(field_for_model, default=str)}"
        + f"\n\nAllowed fields (ids only for progress, do not ask them yet): {json.dumps(field_summary, default=str)}"
        + f"\n\nAlready answered field ids: {list(draft_answers.keys())}"
        + f"\n\nResponse JSON schema: {json.dumps(RESPONSE_SCHEMA)}"
    )

    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    for turn in conversation_snippet[-8:]:
        role = turn["role"]
        if role == "agent":
            role = "assistant"
        if role not in ("user", "assistant", "system"):
            role = "user"
        messages.append({"role": role, "content": turn["content"]})
    messages.append(
        {
            "role": "user",
            "content": (
                f"Current field: {field_for_model['label']} (type={field_for_model['type']}).\n"
                f"Patient answer:\n{patient_message}"
            ),
        }
    )

    content = await _call_chat_completions(messages)
    parsed = _parse_json_content(content)
    status = str(parsed.get("validation_status") or "").lower()

    # Model is the semantic judge. Local checks only enforce format (and cannot mark mash as valid).
    if status in {"invalid", "needs_clarification", "off_topic", "emergency"}:
        parsed["parsed_value"] = None
        parsed["done"] = False
        if not (parsed.get("assistant_message") or "").strip():
            parsed["assistant_message"] = (
                f"That doesn’t look like a valid {field_for_model['label'].lower()}. Please try again."
            )
        parsed.setdefault("field_id", current_field.get("id"))
        return parsed

    ok, err, normalized = validate_field_value(current_field, patient_message, parsed.get("parsed_value"))
    if ok and normalized is not None and normalized != "":
        parsed["parsed_value"] = normalized
        parsed["validation_status"] = "valid"
    else:
        parsed["validation_status"] = "invalid"
        parsed["parsed_value"] = None
        parsed["done"] = False
        parsed["assistant_message"] = err or parsed.get("assistant_message") or (
            f"Please enter a valid {field_for_model['label'].lower()}."
        )

    parsed.setdefault("field_id", current_field.get("id"))
    parsed.setdefault("done", False)
    return parsed


def _parse_json_content(content: str) -> dict[str, Any]:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


async def _call_chat_completions(messages: list[dict[str, str]]) -> str:
    if azure_configured():
        return await _azure_chat(messages)
    return await _openai_chat(messages)


async def _azure_chat(messages: list[dict[str, str]]) -> str:
    url = _azure_chat_url()
    payload: dict[str, Any] = {
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    # o-series (o3-mini) on Azure: no temperature; use max_completion_tokens
    if _is_o_series_deployment():
        payload["max_completion_tokens"] = 800
    else:
        payload["temperature"] = 0.2
        payload["max_tokens"] = 600

    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(
            url,
            headers={
                "api-key": settings.o3_access_token,
                "Content-Type": "application/json",
            },
            json=payload,
        )
        if resp.status_code >= 400:
            logger.error("Azure OpenAI error %s: %s", resp.status_code, resp.text[:500])
            resp.raise_for_status()
        data = resp.json()

    return data["choices"][0]["message"]["content"]


async def _openai_chat(messages: list[dict[str, str]]) -> str:
    async with httpx.AsyncClient(timeout=45.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.openai_model,
                "messages": messages,
                "response_format": {"type": "json_object"},
                "temperature": 0.2,
                "max_tokens": 600,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"]


def _scripted_turn(
    current_field: dict,
    patient_message: str,
    allowed_fields: list[dict],
    draft_answers: dict[str, Any],
) -> dict[str, Any]:
    from app.services.field_validation_service import next_unanswered_field, validate_field_value

    ok, err, normalized = validate_field_value(current_field, patient_message)
    if ok:
        draft_answers = {**draft_answers, current_field["id"]: normalized}
        nxt = next_unanswered_field(allowed_fields, draft_answers)
        if nxt is None:
            return {
                "assistant_message": "Thank you! I have everything I need. Please tap Submit to finish.",
                "field_id": current_field.get("id"),
                "parsed_value": normalized,
                "validation_status": "valid",
                "validation_message": "",
                "done": True,
            }
        return {
            "assistant_message": question_for_field(nxt),
            "field_id": current_field.get("id"),
            "parsed_value": normalized,
            "validation_status": "valid",
            "validation_message": "",
            "done": False,
        }
    return {
        "assistant_message": err or "Could you try that again?",
        "field_id": current_field.get("id"),
        "parsed_value": None,
        "validation_status": "needs_clarification",
        "validation_message": err or "",
        "done": False,
    }


def opening_message(
    patient_name: str,
    practice_name: str,
    first_field: dict,
    visit_summary: str | None = None,
) -> str:
    first = patient_name.split()[0] if patient_name else "there"
    name = assistant_name()
    visit_line = f" This is for your {visit_summary}." if visit_summary else ""
    return (
        f"Hi {first}, I'm {name} — here to help you complete your intake for {practice_name}.{visit_line} "
        f"It should only take a few minutes.\n\n{question_for_field(first_field)}"
    )


def question_for_field(field: dict) -> str:
    label = field.get("label") or "the next question"
    ftype = field.get("type", "text")
    options = field.get("options") or []
    if ftype in ("dropdown", "radio") and options:
        return f"{label}\n\nOptions: {', '.join(options)}"
    if ftype == "select_boxes" and options:
        return f"{label}\n\nYou can choose: {', '.join(options)}"
    if ftype in ("date", "date_entry"):
        blob = f"{field.get('id') or ''} {label}".lower()
        dob_hint = "birth" in blob or bool(re.search(r"\bdob\b", blob))
        extra = " Choose a past date of birth — today and future dates are not allowed." if dob_hint else ""
        return f"{label}\n\nUse the date picker below.{extra}"
    if ftype == "email":
        return f"What is your email address? ({label})"
    if ftype == "phone":
        return f"What is your phone number? ({label})"
    if ftype == "file":
        return f"{label}\n\nPlease attach a file using the button below (PDF, photo, or document)."
    if ftype == "payment":
        return f"{label}\n\nYou can pay at the office — tap below to confirm."
    if ftype == "signature":
        return f"{label}\n\nType your full name to sign."
    if ftype == "checkbox":
        return f"{label} (yes or no)"
    placeholder = field.get("placeholder")
    if placeholder:
        return f"{label}\n\n{placeholder}"
    return label
