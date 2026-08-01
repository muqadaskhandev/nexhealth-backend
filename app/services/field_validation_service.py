"""Deterministic validation for form field answers (agent intake loop)."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

LAYOUT_TYPES = frozenset({"content", "location_logo", "columns", "panel"})
MEDICAL_ALERTS_TYPES = frozenset({"medical_alerts_dropdown", "medical_alerts_radio"})
SKIP_TYPES = LAYOUT_TYPES

# Field types that must be validated locally (no LLM) so junk text never burns tokens.
STRICT_LOCAL_TYPES = frozenset(
    {
        "email",
        "phone",
        "number",
        "date",
        "date_entry",
        "checkbox",
        "dropdown",
        "radio",
        "select_boxes",
        "text",
        "address",
        "preferred_language",
        "insurance",
        "signature",
    }
)

EMAIL_RE = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$", re.I)
PHONE_DIGITS_RE = re.compile(r"^\+?[\d\s\-().]{7,20}$")
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z\s'\-]{1,78}$")
LANGUAGE_RE = re.compile(r"^[A-Za-z][A-Za-z\s\-]{1,48}$")
JUNK_VALUES = frozenset(
    {
        "name",
        "fullname",
        "lastname",
        "first name",
        "last name",
        "full name",
        "email",
        "phone",
        "number",
        "date",
        "address",
        "test",
        "testing",
        "asdf",
        "asd",
        "qwerty",
        "xxx",
        "xxxx",
        "abc",
        "abcd",
        "null",
        "undefined",
        "none",
        "n/a",
        "na",
        "nil",
        "string",
        "text",
        "value",
        "answer",
        "sample",
        "example",
        "foo",
        "bar",
        "baz",
        ".",
        "-",
        "--",
        "...",
    }
)
NAME_SYNC_TARGETS = frozenset({"patient.first_name", "patient.last_name"})
NAME_LABEL_HINTS = ("name", "first name", "last name", "surname", "given name", "full name")


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


def is_name_field(field: dict) -> bool:
    target = (field.get("sync_target") or "").strip()
    if target in NAME_SYNC_TARGETS:
        return True
    label = (field.get("label") or "").strip().lower()
    return any(h in label for h in NAME_LABEL_HINTS)


def should_skip_llm(field: dict) -> bool:
    """Return True when this field can be validated locally without calling the model."""
    ftype = field.get("type", "text")
    if ftype in MEDICAL_ALERTS_TYPES:
        return True
    if ftype == "textarea":
        return False
    return ftype in STRICT_LOCAL_TYPES


def _is_junk(value: str) -> bool:
    cleaned = re.sub(r"\s+", " ", value.strip().lower())
    if cleaned in JUNK_VALUES:
        return True
    if re.fullmatch(r"(.)\1{2,}", cleaned):
        return True
    if re.fullmatch(r"[a-z]{1,2}", cleaned):
        return True
    return False


def _validate_name(label: str, value: str) -> tuple[bool, str | None, Any]:
    val = re.sub(r"\s+", " ", value.strip())
    if _is_junk(val):
        return False, f"Please enter a real {label.lower()} — placeholders like “name” or “test” are not accepted.", None
    if any(ch.isdigit() for ch in val):
        return False, f"Please enter a valid {label.lower()} without numbers.", None
    if not NAME_RE.match(val):
        return False, f"Please enter a valid {label.lower()} using letters only.", None
    if len(val) < 2:
        return False, f"Please enter a valid {label.lower()}.", None
    return True, None, val.title() if val.islower() or val.isupper() else val


def _phone_digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def validate_field_value(field: dict, raw_text: str, parsed_hint: Any = None) -> tuple[bool, str | None, Any]:
    """Validate and normalize a single field answer. Returns (ok, error_message, normalized_value)."""
    ftype = field.get("type", "text")
    label = field.get("label") or "this question"
    text = (raw_text or "").strip()

    if parsed_hint is not None and parsed_hint != "":
        candidate = parsed_hint
    else:
        candidate = text

    if not text and parsed_hint is None and ftype != "checkbox":
        if field.get("required"):
            return False, f"Please provide an answer for {label}.", None
        return True, None, ""

    if ftype == "email":
        val = str(candidate).strip().lower()
        if _is_junk(val) or " " in val or not EMAIL_RE.match(val):
            return False, "Please enter a valid email address (example: name@email.com).", None
        return True, None, val

    if ftype == "phone":
        val = str(candidate).strip()
        if _is_junk(val) or not PHONE_DIGITS_RE.match(val):
            return False, "Please enter a valid phone number using digits only.", None
        digits = _phone_digits(val)
        if len(digits) < 7 or len(digits) > 15:
            return False, "Please enter a valid phone number (7–15 digits).", None
        return True, None, val

    if ftype == "number":
        raw = str(candidate).strip().replace(",", "")
        if _is_junk(raw) or re.search(r"[A-Za-z]", raw):
            return False, f"Please enter a valid number for {label} — letters are not accepted.", None
        try:
            num = float(raw)
        except ValueError:
            return False, f"Please enter a valid number for {label}.", None
        return True, None, num

    if ftype in ("date", "date_entry"):
        if isinstance(candidate, date):
            return True, None, candidate.isoformat()
        raw = str(candidate).strip()
        if _is_junk(raw) or re.fullmatch(r"[A-Za-z\s]+", raw):
            return False, f"Please enter a valid date for {label} (e.g. MM/DD/YYYY).", None
        parsed = _parse_date(raw)
        if parsed is None:
            return False, f"Please enter a valid date for {label} (e.g. MM/DD/YYYY).", None
        # DOB-like fields cannot be in the future
        if is_name_field(field) is False and ("birth" in label.lower() or "dob" in label.lower() or field.get("sync_target") == "patient.date_of_birth"):
            if parsed > date.today():
                return False, "Date of birth cannot be in the future.", None
            if parsed.year < 1900:
                return False, "Please enter a realistic date of birth.", None
        return True, None, parsed.isoformat()

    if ftype == "checkbox":
        low = str(candidate).strip().lower() if candidate is not None else text.lower()
        if low in ("yes", "true", "y", "1", "checked"):
            return True, None, True
        if low in ("no", "false", "n", "0", "unchecked"):
            return True, None, False
        return False, f"Please answer yes or no for {label}.", None

    if ftype in ("dropdown", "radio"):
        options = field.get("options") or []
        val = str(candidate).strip()
        if _is_junk(val):
            return False, f"Please choose one of: {', '.join(options)}." if options else f"Please choose a valid option for {label}.", None
        if options and val not in options:
            match = next((o for o in options if o.lower() == val.lower()), None)
            if match:
                return True, None, match
            return False, f"Please choose one of: {', '.join(options)}.", None
        if not options and not val:
            return False, f"Please provide an answer for {label}.", None
        return True, None, val

    if ftype == "select_boxes":
        options = field.get("options") or []
        if isinstance(candidate, list):
            vals = [str(v).strip() for v in candidate if str(v).strip()]
        else:
            vals = [v.strip() for v in re.split(r"[,;]", text) if v.strip()]
        if not vals and field.get("required"):
            return False, f"Please choose at least one option for {label}.", None
        if options:
            bad = [v for v in vals if v not in options and not any(o.lower() == v.lower() for o in options)]
            if bad:
                return False, f"Please choose from: {', '.join(options)}.", None
            vals = [next((o for o in options if o.lower() == v.lower()), v) for v in vals]
        return True, None, vals

    if ftype in MEDICAL_ALERTS_TYPES:
        if not isinstance(candidate, dict):
            return False, "Please complete the medical history section.", None
        for _cat, block in candidate.items():
            if not isinstance(block, dict):
                continue
            responses = block.get("responses") or {}
            for _rid, ans in responses.items():
                if ans not in ("yes", "no"):
                    return False, "Please answer Yes or No for each medical history item.", None
        return True, None, candidate

    if ftype == "preferred_language":
        val = re.sub(r"\s+", " ", str(candidate).strip())
        if _is_junk(val) or not LANGUAGE_RE.match(val):
            return False, "Please enter a valid language (letters only), e.g. English.", None
        return True, None, val.title()

    if ftype in ("text", "textarea", "address", "insurance", "signature"):
        val = re.sub(r"\s+", " ", str(candidate).strip())
        if not val:
            if field.get("required"):
                return False, f"Please provide an answer for {label}.", None
            return True, None, ""
        if _is_junk(val):
            return False, f"Please enter a real answer for {label} — placeholders are not accepted.", None
        if is_name_field(field) or ftype == "text" and ("name" in label.lower()):
            return _validate_name(label, val)
        if ftype == "address":
            if len(val) < 5 or not re.search(r"[A-Za-z]", val):
                return False, "Please enter a valid street address.", None
            if val.isdigit():
                return False, "Please enter a valid street address — not just numbers.", None
        min_len = field.get("min_length")
        max_len = field.get("max_length")
        if min_len and len(val) < min_len:
            return False, f"Please enter at least {min_len} characters for {label}.", None
        if max_len and len(val) > max_len:
            return False, f"Please keep {label} under {max_len} characters.", None
        if ftype == "text" and re.fullmatch(r"\d+", val) and "zip" not in label.lower() and "code" not in label.lower():
            return False, f"Please enter a valid text answer for {label} — not only numbers.", None
        return True, None, val

    # file / payment — still reject obvious junk
    val = str(candidate).strip()
    if _is_junk(val):
        return False, f"Please provide a valid answer for {label}.", None
    return True, None, val


def progress_counts(fields: list[dict], draft: dict[str, Any]) -> tuple[int, int]:
    """Return (answered_count, total_collectible)."""
    collectible = intake_fields(fields, draft)
    answered = 0
    for f in collectible:
        fid = f.get("id")
        if fid and _has_value(f, draft.get(fid)):
            answered += 1
    return answered, len(collectible)
