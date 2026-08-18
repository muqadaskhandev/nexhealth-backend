"""Build patient-facing form / agent intake links for outbound messages."""
from __future__ import annotations

import uuid

from app.config import settings
from app.services.booking_availability_service import practice_slug

IntakeMode = str  # "form" | "agent" | "both"


def build_booking_path(practice_name: str, practice_id: uuid.UUID, location_id: uuid.UUID | None = None) -> str:
    """Relative URL to public booking. `mode=both` lets the patient pick classic or Angelina chat."""
    slug = practice_slug(practice_name or "")
    qs = [f"lid={str(practice_id)[:8]}"]
    if location_id is not None:
        qs.append(f"location_ids={location_id}")
    qs.append("mode=both")
    return f"/appt/{slug}?{'&'.join(qs)}"


def build_intake_links(raw_token: str, intake_mode: str = "agent") -> dict[str, str]:
    base = settings.frontend_url.rstrip("/")
    form_link = f"{base}/forms/{raw_token}"
    agent_link = f"{base}/agent/{raw_token}"
    mode = intake_mode if intake_mode in ("form", "agent", "both") else "agent"

    if mode == "form":
        primary = form_link
        secondary = ""
    elif mode == "both":
        primary = agent_link
        secondary = form_link
    else:
        primary = agent_link
        secondary = ""

    return {
        "mode": mode,
        "primary_link": primary,
        "form_link": form_link,
        "agent_link": agent_link,
        "secondary_link": secondary,
    }


def format_intake_sms_body(
    *,
    form_names: str,
    links: dict[str, str],
    custom_message: str | None,
    assistant_name: str,
) -> str:
    if custom_message and custom_message.strip():
        intro = custom_message.strip()
    elif links["mode"] == "agent":
        intro = f"Hi! {assistant_name} will help you complete your intake form(s): {form_names}"
    elif links["mode"] == "both":
        intro = f"Please complete your form(s): {form_names}. Chat with {assistant_name} or use the classic form."
    else:
        intro = f"Please fill out the following form(s): {form_names}"

    lines = [intro, links["primary_link"]]
    if links["secondary_link"]:
        lines.append(f"Classic form: {links['secondary_link']}")
    return "\n".join(lines)
