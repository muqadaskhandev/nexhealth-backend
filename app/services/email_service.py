"""Transactional email delivery via AWS SES.

In development (SES_ENABLED=false) messages are printed to stdout so flows
are testable without AWS credentials. Outside production, a failed SES send
also falls back to stdout so local invites are not blocked by AWS misconfig.
"""
from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)


class EmailDeliveryError(RuntimeError):
    """Raised when an email cannot be delivered (production SES failures)."""


def _print_email(*, to: str, subject: str, html: str, text: str) -> None:
    print(f"\n[email] To: {to}\nSubject: {subject}\n{text}\nLink in HTML:\n{html}\n")


def _send_via_ses(*, to: str, subject: str, html: str, text: str) -> None:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    client = boto3.client(
        "ses",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id or None,
        aws_secret_access_key=settings.aws_secret_access_key or None,
    )
    try:
        client.send_email(
            Source=f"{settings.ses_from_name} <{settings.ses_from_email}>",
            Destination={"ToAddresses": [to]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": text, "Charset": "UTF-8"},
                    "Html": {"Data": html, "Charset": "UTF-8"},
                },
            },
        )
    except (BotoCoreError, ClientError) as exc:
        logger.exception("SES send failed for %s", to)
        raise EmailDeliveryError(
            "Failed to send email. Check AWS SES configuration and verified from-address."
        ) from exc


def send_email(*, to: str, subject: str, html: str, text: str) -> None:
    if settings.ses_enabled:
        try:
            _send_via_ses(to=to, subject=subject, html=html, text=text)
            return
        except EmailDeliveryError:
            if settings.is_production:
                raise
            logger.warning(
                "SES send failed for %s; falling back to stdout (non-production)", to
            )
    _print_email(to=to, subject=subject, html=html, text=text)


def send_practice_admin_invite(
    *,
    to: str,
    practice_name: str,
    invite_url: str,
    admin_name: str,
) -> None:
    subject = f"You're invited to manage {practice_name} on NextHealth"
    text = (
        f"Hi {admin_name},\n\n"
        f"You've been invited as Practice Admin for {practice_name}.\n"
        f"Set up your account: {invite_url}\n\n"
        "This link expires in 72 hours.\n"
    )
    html = f"""
    <p>Hi {admin_name},</p>
    <p>You've been invited as <strong>Practice Admin</strong> for
    <strong>{practice_name}</strong> on NextHealth.</p>
    <p><a href="{invite_url}">Accept invitation &amp; set password</a></p>
    <p>This link expires in 72 hours.</p>
  """
    send_email(to=to, subject=subject, html=html, text=text)


def send_staff_invite(
    *,
    to: str,
    practice_name: str,
    invite_url: str,
    inviter_name: str,
) -> None:
    subject = f"Join {practice_name} on NextHealth"
    text = (
        f"You've been invited to join {practice_name} by {inviter_name}.\n"
        f"Accept your invite: {invite_url}\n"
    )
    html = f"""
    <p>You've been invited to join <strong>{practice_name}</strong>
    by {inviter_name}.</p>
    <p><a href="{invite_url}">Accept invitation &amp; set password</a></p>
  """
    send_email(to=to, subject=subject, html=html, text=text)


def send_password_reset(*, to: str, reset_url: str) -> None:
    subject = "Reset your NextHealth password"
    text = f"Reset your password: {reset_url}\n"
    html = f'<p><a href="{reset_url}">Reset your password</a></p>'
    send_email(to=to, subject=subject, html=html, text=text)


def send_form_intake(
    *,
    to: str,
    patient_name: str,
    practice_name: str,
    form_names: str,
    primary_link: str,
    secondary_link: str = "",
    intake_mode: str = "agent",
    assistant_name: str = "Angelina",
    custom_note: str | None = None,
) -> None:
    """Email patient a form or chat-intake link (SES when enabled)."""
    if intake_mode == "agent":
        subject = f"Complete your intake — {practice_name}"
        cta = f"Chat with {assistant_name}"
        intro = custom_note.strip() if custom_note and custom_note.strip() else (
            f"Hi {patient_name},\n\n{assistant_name} will guide you through: {form_names}."
        )
    elif intake_mode == "both":
        subject = f"Complete your forms — {practice_name}"
        cta = f"Start chat with {assistant_name}"
        intro = custom_note.strip() if custom_note and custom_note.strip() else (
            f"Hi {patient_name},\n\nPlease complete: {form_names}. "
            f"You can chat with {assistant_name} or use the classic form."
        )
    else:
        subject = f"Forms to complete — {practice_name}"
        cta = "Open forms"
        intro = custom_note.strip() if custom_note and custom_note.strip() else (
            f"Hi {patient_name},\n\nPlease complete the following form(s): {form_names}."
        )

    text = f"{intro}\n\n{cta}: {primary_link}\n"
    html_parts = [f"<p>{intro.replace(chr(10), '<br/>')}</p>", f'<p><a href="{primary_link}">{cta}</a></p>']
    if secondary_link:
        text += f"\nClassic form: {secondary_link}\n"
        html_parts.append(f'<p><a href="{secondary_link}">Open classic form</a></p>')
    html = "\n".join(html_parts)
    send_email(to=to, subject=subject, html=html, text=text)

