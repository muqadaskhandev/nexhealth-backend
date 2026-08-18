"""Deterministic validation for form field answers (agent intake loop)."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

LAYOUT_TYPES = frozenset({"content", "location_logo", "columns", "panel"})
MEDICAL_ALERTS_TYPES = frozenset({"medical_alerts_dropdown", "medical_alerts_radio"})
SKIP_TYPES = LAYOUT_TYPES

# Format-only types stay local (dates, emails, chips). Semantic types go to the model.
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
        "file",
        "payment",
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
NAME_LABEL_HINTS = ("first name", "last name", "surname", "given name", "full name", "middle name")
DOB_SYNC_TARGETS = frozenset({"patient.date_of_birth", "patient.dob"})
MAX_DOB_AGE_YEARS = 120


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
        return isinstance(value, bool)
    if ftype == "medical_alerts_dropdown":
        # Tag picker: omitted catalog items mean "no"; an object is enough.
        return isinstance(value, dict)
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
    fid = (field.get("id") or "").strip().lower()
    if "birth" in label or fid in ("dob", "date_of_birth"):
        return False
    return any(h in label for h in NAME_LABEL_HINTS)


def is_dob_field(field: dict) -> bool:
    target = (field.get("sync_target") or "").strip()
    if target in DOB_SYNC_TARGETS:
        return True
    blob = f"{field.get('id') or ''} {field.get('label') or ''}".lower()
    return "birth" in blob or re.search(r"\bdob\b", blob) is not None


def _dob_error(parsed: date) -> str | None:
    today = date.today()
    if parsed >= today:
        return "Date of birth cannot be today or in the future. Please pick a past date (for example, 03/15/1990)."
    try:
        oldest = today.replace(year=today.year - MAX_DOB_AGE_YEARS)
    except ValueError:
        oldest = today.replace(month=2, day=28, year=today.year - MAX_DOB_AGE_YEARS)
    if parsed < oldest:
        return "That doesn't look like a real date of birth. Please enter a realistic past date."
    return None


def should_skip_llm(field: dict) -> bool:
    """True when format can be checked locally (picker / email / date). Semantic text goes to the model."""
    ftype = field.get("type", "text")
    if ftype in MEDICAL_ALERTS_TYPES:
        return True
    return ftype in STRICT_LOCAL_TYPES


_VOWELS = set("aeiouyAEIOUY")
_KEYBOARD_MASH = re.compile(
    r"asdf+|qwer+|zxcv+|hjkl+|qazwsx|wsxedc|1234+|abcd+|fghj+|uiop+",
    re.I,
)


def _is_junk(value: str, *, allow_short: bool = False) -> bool:
    cleaned = re.sub(r"\s+", " ", value.strip().lower())
    if cleaned in JUNK_VALUES:
        return True
    if re.fullmatch(r"(.)\1{2,}", cleaned):
        return True
    if not allow_short and re.fullmatch(r"[a-z]{1,2}", cleaned):
        return True
    if _KEYBOARD_MASH.search(re.sub(r"[\s'\-]", "", cleaned)):
        return True
    return False


# Common English / given-name letter pairs. Keyboard mash almost never uses these.
_NAME_LIKE_BIGRAMS = frozenset(
    "th he an in er re on at en nd st es or te ed is it al ar nt ng se ha as ou "
    "le ve co me de hi ri ro ic ne ea ra ce li ch el la ll be ma na sh ti ca pa "
    "sa da ta mi ki ja jo ka ke ko lu ly ny ph qu sc sk sm sn sp sw tw wh ye yo "
    "br cr dr fr gr pr tr cl fl gl pl sl bl kn ck gh mb mp nk ld lt rd rk rm rn "
    "rs rt wn ia ie io ou ay ey oy oo ee ah eh oh ul um un ur us ut wa we wi wo "
    "ya ye za ze zo ad af ag ai ak am ao ap aq au av aw ax az ba bi bo bu by "
    "di do du em eu fa fe fi fo fu ga ge gi go gu ho hu hy id if ig il im ip ir "
    "je ji ju lo ni no nu oc od of og oh ok ol om op os ot ov ox oz pe pi po pu "
    "qa qi ra ru si so su to tu va vi vo vu xi za zu "
    "mu uq qa ad da as ng uy".split()
)


def _name_bigrams_look_real(part: str) -> bool:
    compact = re.sub(r"[^a-z]", "", part.lower())
    if len(compact) < 5:
        return True
    pairs = [compact[i : i + 2] for i in range(len(compact) - 1)]
    hits = sum(1 for p in pairs if p in _NAME_LIKE_BIGRAMS)
    ratio = hits / max(len(pairs), 1)
    # Long mash like "fkyitkfyt" can accidentally include "yi"+"it"; require more overlap.
    if len(compact) >= 7:
        return hits >= 3 and ratio >= 0.35
    return hits >= 2 or ratio >= 0.4


def _name_looks_implausible(value: str) -> bool:
    """Catch keyboard mash / gibberish that still matches [A-Za-z]."""
    parts = [p for p in re.split(r"[\s'\-]+", value) if p]
    if not parts or len(parts) > 5:
        return True
    for part in parts:
        if len(part) == 1:
            continue
        if len(part) > 16:
            return True
        if len(part) >= 3 and not any(ch in _VOWELS for ch in part):
            return True
        run = 0
        for ch in part:
            if ch in _VOWELS:
                run = 0
            elif ch.isalpha():
                run += 1
                if run >= 5:
                    return True
        if not _name_bigrams_look_real(part):
            return True
    return False


def _looks_like_gibberish(value: str, *, allow_acronyms: bool = True) -> bool:
    """Reject mashed keys for any free-text field without sending the answer to the LLM."""
    raw = re.sub(r"\s+", " ", str(value).strip())
    if not raw:
        return False
    if _is_junk(raw, allow_short=True):
        return True
    words = re.findall(r"[A-Za-z]+", raw)
    if not words:
        return False
    for word in words:
        if allow_acronyms and word.isupper() and 2 <= len(word) <= 6:
            continue
        if _name_looks_implausible(word):
            return True
    return False


def _please_retry(label: str, hint: str | None = None) -> str:
    pretty = (label or "this question").strip() or "this question"
    if hint:
        return f"That doesn’t look like a valid answer for {pretty}. {hint}"
    return f"That doesn’t look like a valid answer for {pretty}. Please enter real information."


def _validate_name(label: str, value: str) -> tuple[bool, str | None, Any]:
    val = re.sub(r"\s+", " ", value.strip())
    pretty = label.lower() if label.lower() not in {"name", "this question"} else "name"
    retry = (
        f"That doesn’t look like a real {pretty}. "
        f"Please enter a valid {pretty} using letters only (for example, Jane or Mary Alice)."
    )
    if _is_junk(val, allow_short=True) or _name_looks_implausible(val):
        return False, retry, None
    if any(ch.isdigit() for ch in val):
        return False, f"Please enter a valid {pretty} without numbers.", None
    if not NAME_RE.match(val):
        return False, f"Please enter a valid {pretty} using letters only.", None
    if len(val) < 2:
        return False, f"Please enter a valid {pretty}.", None
    return True, None, val.title() if val.islower() or val.isupper() else val


def _phone_digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _option_token(value: str) -> str:
    """Normalize option text for tolerant matching (case/punctuation/spacing)."""
    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    # Trim common trailing punctuation so "No." matches "No"
    text = re.sub(r"[.!?;:,]+$", "", text)
    return text


def _match_option(options: list[str], value: str) -> str | None:
    if not options:
        return None
    needle = _option_token(value)
    if not needle:
        return None
    for opt in options:
        if _option_token(opt) == needle:
            return opt
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

    if not text and parsed_hint is None and ftype != "checkbox":
        if field.get("required"):
            return False, f"Please provide an answer for {label}.", None
        return True, None, ""

    if ftype == "email":
        val = str(candidate).strip().lower()
        local = val.split("@", 1)[0] if "@" in val else val
        if (
            _is_junk(val)
            or _is_junk(local, allow_short=True)
            or _looks_like_gibberish(local)
            or " " in val
            or not EMAIL_RE.match(val)
        ):
            return False, "Please enter a valid email address (example: jane@email.com).", None
        return True, None, val

    if ftype == "phone":
        val = str(candidate).strip()
        digits = _phone_digits(val)
        if _is_junk(val) or not PHONE_DIGITS_RE.match(val):
            return False, "Please enter a valid phone number using digits only.", None
        if len(digits) < 7 or len(digits) > 15:
            return False, "Please enter a valid phone number (7–15 digits).", None
        if re.fullmatch(r"(\d)\1{6,}", digits):
            return False, "Please enter a real phone number — repeating digits are not accepted.", None
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
            parsed = candidate
        else:
            raw = str(candidate).strip()
            if _is_junk(raw) or re.fullmatch(r"[A-Za-z\s]+", raw):
                return False, f"Please enter a valid date for {label} (e.g. MM/DD/YYYY).", None
            parsed = _parse_date(raw)
            if parsed is None:
                return False, f"Please enter a valid date for {label} (e.g. MM/DD/YYYY).", None
        if is_dob_field(field):
            dob_err = _dob_error(parsed)
            if dob_err:
                return False, dob_err, None
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
        if options:
            match = _match_option(options, val)
            if match is not None:
                return True, None, match
            return False, f"Please choose one of: {', '.join(options)}.", None
        if not val or _looks_like_gibberish(val):
            return False, f"Please choose a valid option for {label}." if not options else f"Please choose one of: {', '.join(options)}.", None
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
            bad = [v for v in vals if _match_option(options, v) is None]
            if bad:
                return False, f"Please choose from: {', '.join(options)}.", None
            vals = [(_match_option(options, v) or v) for v in vals]
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
            for item in block.get("writeIns") or []:
                w = str(item).strip()
                if w and (_is_junk(w, allow_short=True) or _looks_like_gibberish(w)):
                    return False, "Please enter a real condition, allergy, or medication name.", None
        return True, None, candidate

    if ftype == "preferred_language":
        val = re.sub(r"\s+", " ", str(candidate).strip())
        if _is_junk(val) or _looks_like_gibberish(val) or not LANGUAGE_RE.match(val):
            return False, "Please enter a valid language (letters only), e.g. English.", None
        return True, None, val.title()

    if ftype == "signature":
        val = re.sub(r"\s+", " ", str(candidate).strip())
        if not val:
            if field.get("required"):
                return False, "Please type your full name to sign.", None
            return True, None, ""
        return _validate_name("name", val)

    if ftype == "file":
        val = str(candidate).strip()
        if not val:
            if field.get("required"):
                return False, "Please attach a file using the upload button.", None
            return True, None, ""
        if _is_junk(val):
            return False, "Please attach a PDF, photo, or document.", None
        if not (val.startswith("/uploads/") or val.startswith("http://") or val.startswith("https://")):
            return False, "Please attach a PDF, photo, or document using the upload button.", None
        return True, None, val

    if ftype == "payment":
        val = str(candidate).strip().lower().replace("-", "_").replace(" ", "_")
        if val in ("pay_at_office", "paid", "pay_at_the_office", "office"):
            return True, None, "pay_at_office"
        if not field.get("required") and not val:
            return True, None, ""
        return False, "Tap the button below if you'll pay at the office.", None

    if ftype in ("text", "textarea", "address", "insurance"):
        val = re.sub(r"\s+", " ", str(candidate).strip())
        if not val:
            if field.get("required"):
                return False, f"Please provide an answer for {label}.", None
            return True, None, ""
        if is_name_field(field) or (ftype == "text" and "name" in label.lower()):
            return _validate_name(label, val)
        if _is_junk(val) or _looks_like_gibberish(val):
            return False, _please_retry(label, "Please enter real information, not random letters."), None
        if ftype == "address":
            if len(val) < 5 or not re.search(r"[A-Za-z]", val):
                return False, "Please enter a valid street address.", None
            if val.isdigit():
                return False, "Please enter a valid street address — not just numbers.", None
            if not re.search(r"[A-Za-z]{2,}", val):
                return False, "Please enter a valid street address.", None
        if ftype == "textarea" and len(val) < 3:
            return False, _please_retry(label), None
        min_len = field.get("min_length")
        max_len = field.get("max_length")
        if min_len and len(val) < min_len:
            return False, f"Please enter at least {min_len} characters for {label}.", None
        if max_len and len(val) > max_len:
            return False, f"Please keep {label} under {max_len} characters.", None
        if ftype == "text" and re.fullmatch(r"\d+", val) and "zip" not in label.lower() and "code" not in label.lower():
            return False, f"Please enter a valid text answer for {label} — not only numbers.", None
        return True, None, val

    # Unknown types — still reject mashed keys locally; do not send them to the model.
    val = str(candidate).strip()
    if _is_junk(val) or _looks_like_gibberish(val):
        return False, _please_retry(label), None
    return True, None, val


_REVIEW_MEDICAL_TITLES = {
    "condition": "Conditions",
    "allergy": "Allergies",
    "medication": "Medications",
}


def _medical_alert_label_map(catalog: dict | None) -> dict[str, str]:
    labels: dict[str, str] = {}
    if not catalog:
        return labels
    for entries in catalog.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            eid = entry.get("id")
            elabel = entry.get("label")
            if eid is None:
                continue
            key = str(eid).lower()
            name = str(elabel) if elabel else str(eid)
            labels[key] = name
            labels[key.replace("-", "")] = name
    return labels


def format_medical_alerts_review(value: Any, catalog: dict | None = None) -> str:
    """Human-readable conditions / allergies / medications for review UI."""
    if not isinstance(value, dict):
        return "None listed"
    labels = _medical_alert_label_map(catalog)
    parts: list[str] = []
    for cat, title in _REVIEW_MEDICAL_TITLES.items():
        block = value.get(cat) or {}
        if not isinstance(block, dict):
            continue
        names: list[str] = []
        stored = block.get("labels") if isinstance(block.get("labels"), dict) else {}
        responses = block.get("responses") or {}
        if isinstance(responses, dict):
            for rid, ans in responses.items():
                if str(ans).lower() != "yes":
                    continue
                key = str(rid)
                name = stored.get(key) or stored.get(key.lower())
                if not name:
                    key_l = key.lower()
                    name = labels.get(key_l) or labels.get(key_l.replace("-", ""))
                names.append(str(name) if name else key)
        write_ins = block.get("writeIns") or []
        if isinstance(write_ins, list):
            names.extend(str(w).strip() for w in write_ins if str(w).strip())
        if names:
            parts.append(f"{title}: {', '.join(names)}")
    return " · ".join(parts) if parts else "None listed"


def attach_medical_alert_labels(value: Any, catalog: dict | None) -> Any:
    """Copy catalog names onto selected ids so review works even if the catalog later changes."""
    if not isinstance(value, dict):
        return value
    labels = _medical_alert_label_map(catalog)
    out: dict[str, Any] = {}
    for cat, block in value.items():
        if not isinstance(block, dict):
            out[cat] = block
            continue
        stored = dict(block.get("labels") or {}) if isinstance(block.get("labels"), dict) else {}
        responses = block.get("responses") or {}
        if isinstance(responses, dict):
            for rid in responses:
                key = str(rid)
                if stored.get(key) or stored.get(key.lower()):
                    continue
                key_l = key.lower()
                name = labels.get(key_l) or labels.get(key_l.replace("-", ""))
                if name:
                    stored[key] = name
        next_block = dict(block)
        if stored:
            next_block["labels"] = stored
        out[cat] = next_block
    return out


def repair_stale_medical_alert_ids(fields: list[dict], draft: dict[str, Any], catalog: dict | None) -> str | None:
    """Drop selected catalog ids that are not in the live list. Returns the field id if recapture is needed."""
    labels = _medical_alert_label_map(catalog)
    recapture: str | None = None
    for f in fields:
        if f.get("type") not in MEDICAL_ALERTS_TYPES:
            continue
        fid = f.get("id")
        if not fid:
            continue
        val = draft.get(fid)
        if not isinstance(val, dict):
            continue
        next_val: dict[str, Any] = {}
        dropped = False
        for cat, block in val.items():
            if not isinstance(block, dict):
                next_val[cat] = block
                continue
            stored = block.get("labels") if isinstance(block.get("labels"), dict) else {}
            responses = block.get("responses") or {}
            keep: dict[str, Any] = {}
            if isinstance(responses, dict):
                for rid, ans in responses.items():
                    key = str(rid)
                    key_l = key.lower()
                    if (
                        stored.get(key)
                        or stored.get(key_l)
                        or labels.get(key_l)
                        or labels.get(key_l.replace("-", ""))
                    ):
                        keep[rid] = ans
                    else:
                        dropped = True
            next_block = dict(block)
            next_block["responses"] = keep
            next_val[cat] = next_block
        draft[fid] = next_val
        if dropped:
            recapture = fid
    return recapture


def review_items(fields: list[dict], draft: dict[str, Any], catalog: dict | None = None) -> list[dict[str, Any]]:
    """Answered intake fields for the patient review-before-submit screen."""
    items: list[dict[str, Any]] = []
    for f in intake_fields(fields, draft):
        fid = f.get("id")
        if not fid:
            continue
        val = draft.get(fid)
        if not _has_value(f, val):
            continue
        ftype = f.get("type") or "text"
        if ftype in MEDICAL_ALERTS_TYPES:
            val = format_medical_alerts_review(val, catalog)
        items.append(
            {
                "field_id": fid,
                "label": f.get("label") or "",
                "type": ftype,
                "value": val,
            }
        )
    return items


def progress_counts(fields: list[dict], draft: dict[str, Any]) -> tuple[int, int]:
    """Return (answered_count, total_collectible)."""
    collectible = intake_fields(fields, draft)
    answered = 0
    for f in collectible:
        fid = f.get("id")
        if fid and _has_value(f, draft.get(fid)):
            answered += 1
    return answered, len(collectible)
