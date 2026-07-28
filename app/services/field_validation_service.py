"""Deterministic validation for form field answers (agent intake loop)."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

LAYOUT_TYPES = frozenset({"content", "location_logo", "columns", "panel"})
MEDICAL_ALERTS_TYPES = frozenset({"medical_alerts_dropdown", "medical_alerts_radio"})
SKIP_TYPES = LAYOUT_TYPES

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PHONE_RE = re.compile(r"^[\d\s\-().+]{7,20}$")


def field_is_visible(field: dict, answers: dict[str, Any]) -> bool:
    cond_id = field.get("conditional_field_id")
    if not cond_id:
        return True
    expected = field.get("conditional_value", "")
    actual = answers.get(cond_id)
    if actual is None:
        return False
    if isinstance(actual, list):
        return expected in actual
    if isinstance(actual, bool):
        return actual == (expected.lower() == "true")
    return str(actual) == expected


def intake_fields(fields: list[dict], answers: dict[str, Any] | None = None) -> list[dict]:
    """Fields the agent should collect (excludes layout-only)."""
    answers = answers or {}
    out: list[dict] = []
    for f in fields:
        if f.get("type") in SKIP_TYPES:
            continue
        if not field_is_visible(f, answers):
            continue
        out.append(f)
    return out


def next_unanswered_field(fields: list[dict], draft: dict[str, Any]) -> dict | None:
    for f in intake_fields(fields, draft):
        fid = f.get("id")
        if not fid:
            continue
        if f.get("required") and not _has_value(f, draft.get(fid)):
            return f
    for f in intake_fields(fields, draft):
        fid = f.get("id")
        if not fid:
            continue
        if not f.get("required") and fid not in draft:
            return f
    return None


def has_value(field: dict, value: Any) -> bool:
    return _has_value(field, value)


def _has_value(field: dict, value: Any) -> bool:
    if value is None:
        return False
    ftype = field.get("type", "text")
    if ftype == "checkbox":
        return value is True
    if ftype in MEDICAL_ALERTS_TYPES:
        if not isinstance(value, dict):
            return False
        if not field.get("required"):
            for _cat, block in value.items():
                if isinstance(block, dict) and (block.get("responses") or block.get("writeIns")):
                    return True
            return False
        # Required: every catalog item needs yes/no — completeness checked at submit with catalog
        for _cat, block in value.items():
            if not isinstance(block, dict):
                continue
            responses = block.get("responses") or {}
            if responses:
                return True
        return False
    if isinstance(value, list):
        return len(value) > 0
    if isinstance(value, dict):
        return bool(value)
    return str(value).strip() != ""


def _parse_date(text: str) -> date | None:
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def validate_field_value(field: dict, raw_text: str, parsed_hint: Any = None) -> tuple[bool, str | None, Any]:
    """Validate and normalize a single field answer. Returns (ok, error_message, normalized_value)."""
    ftype = field.get("type", "text")
    label = field.get("label") or "this question"
    text = (raw_text or "").strip()

    if parsed_hint is not None and parsed_hint != "":
        candidate = parsed_hint
    else:
        candidate = text

    if not text and ftype != "checkbox":
        if field.get("required"):
            return False, f"Please provide an answer for {label}.", None
        return True, None, ""

    if ftype in ("text", "textarea", "address", "preferred_language", "insurance", "signature"):
        val = str(candidate).strip()
        min_len = field.get("min_length")
        max_len = field.get("max_length")
        if min_len and len(val) < min_len:
            return False, f"Please enter at least {min_len} characters for {label}.", None
        if max_len and len(val) > max_len:
            return False, f"Please keep {label} under {max_len} characters.", None
        return True, None, val

    if ftype == "email":
        val = str(candidate).strip().lower()
        if not EMAIL_RE.match(val):
            return False, "Please enter a valid email address.", None
        return True, None, val

    if ftype == "phone":
        val = str(candidate).strip()
        if not PHONE_RE.match(val):
            return False, "Please enter a valid phone number.", None
        return True, None, val

    if ftype == "number":
        try:
            num = float(str(candidate).replace(",", ""))
        except ValueError:
            return False, f"Please enter a valid number for {label}.", None
        return True, None, num

    if ftype in ("date", "date_entry"):
        if isinstance(candidate, date):
            return True, None, candidate.isoformat()
        parsed = _parse_date(str(candidate))
        if parsed is None:
            return False, f"Please enter a valid date for {label} (e.g. MM/DD/YYYY).", None
        return True, None, parsed.isoformat()

    if ftype == "checkbox":
        low = text.lower()
        if low in ("yes", "true", "y", "1", "checked"):
            return True, None, True
        if low in ("no", "false", "n", "0", "unchecked", ""):
            return True, None, False
        return False, f"Please answer yes or no for {label}.", None

    if ftype in ("dropdown", "radio"):
        options = field.get("options") or []
        val = str(candidate).strip()
        if options and val not in options:
            # fuzzy match
            match = next((o for o in options if o.lower() == val.lower()), None)
            if match:
                return True, None, match
            return False, f"Please choose one of: {', '.join(options)}.", None
        return True, None, val

    if ftype == "select_boxes":
        options = field.get("options") or []
        if isinstance(candidate, list):
            vals = [str(v).strip() for v in candidate if str(v).strip()]
        else:
            vals = [v.strip() for v in re.split(r"[,;]", text) if v.strip()]
        if options:
            bad = [v for v in vals if v not in options]
            if bad:
                return False, f"Please choose from: {', '.join(options)}.", None
        return True, None, vals

    if ftype in MEDICAL_ALERTS_TYPES:
        if not isinstance(candidate, dict):
            return False, "Please complete the medical history section.", None
        for _cat, block in candidate.items():
            if not isinstance(block, dict):
                continue
            responses = block.get("responses") or {}
            for rid, ans in responses.items():
                if ans not in ("yes", "no"):
                    return False, "Please answer Yes or No for each medical history item.", None
        return True, None, candidate

    # file, payment — accept raw text in agent v1
    return True, None, str(candidate).strip()


def progress_counts(fields: list[dict], draft: dict[str, Any]) -> tuple[int, int]:
    """Return (answered_count, total_collectible)."""
    collectible = intake_fields(fields, draft)
    answered = 0
    for f in collectible:
        fid = f.get("id")
        if fid and _has_value(f, draft.get(fid)):
            answered += 1
    return answered, len(collectible)
