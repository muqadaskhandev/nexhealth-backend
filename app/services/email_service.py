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

    # Plain-text fallback
    text = f"{intro}\n\n{cta}: {primary_link}\n"
    if secondary_link:
        text += f"\nClassic form: {secondary_link}\n"

    # Simple "email card" layout (inline styles for broad client support)
    intro_html = intro.replace(chr(10), "<br/>")
    cta_button = (
        f'<a href="{primary_link}" '
        f'style="display:inline-block;background:#0d9488;color:#ffffff;'
        f'padding:12px 18px;border-radius:8px;text-decoration:none;font-weight:600;" '
        f'target="_blank" rel="noopener"> {cta} </a>'
    )

    secondary_html = ""
    if secondary_link:
        secondary_html = (
            f'<div style="margin-top:14px;text-align:center;">'
            f'<a href="{secondary_link}" style="color:#0d9488;text-decoration:underline;font-size:14px;" '
            f'target="_blank" rel="noopener">Open classic form</a>'
            f"</div>"
        )

    html = f"""
    <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background:#f9fafb;padding:24px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="600" style="max-width:600px;background:#ffffff;border-radius:16px;overflow:hidden;">
            <tr>
              <td style="padding:22px 22px 10px 22px;">
                <div style="font-family:Arial,Helvetica,sans-serif;">
                  <div style="font-size:12px;letter-spacing:0.08em;text-transform:uppercase;color:#6b7280;">NextHealth</div>
                  <div style="margin-top:8px;font-size:22px;font-weight:700;color:#111827;">Complete your intake</div>
                  <div style="margin-top:6px;font-size:14px;color:#4b5563;">{practice_name}</div>
                </div>
              </td>
            </tr>

            <tr>
              <td style="padding:8px 22px 4px 22px;">
                <div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.5;color:#374151;">
                  {intro_html}
                </div>
              </td>
            </tr>

            <tr>
              <td style="padding:16px 22px 22px 22px;">
                <div style="text-align:center;">
                  {cta_button}
                </div>
                {secondary_html}
              </td>
            </tr>

            <tr>
              <td style="padding:0 22px 22px 22px;">
                <div style="font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:1.4;color:#6b7280;text-align:center;">
                  If you need help, you can reply to this email.
                </div>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
    """.strip()

    send_email(to=to, subject=subject, html=html, text=text)


def send_booking_confirmation(
    *,
    to: str,
    patient_name: str,
    practice_name: str,
    location_name: str,
    location_address: str,
    appointment_type: str,
    provider_name: str,
    when: str,
) -> None:
    """Email the patient that their online booking is confirmed."""
    subject = f"Your appointment is confirmed — {practice_name}"
    where = location_name if not location_address else f"{location_name}, {location_address}"
    text = (
        f"Hi {patient_name},\n\n"
        f"Your appointment with {practice_name} is confirmed.\n\n"
        f"{appointment_type} with {provider_name}\n"
        f"{when}\n"
        f"{where}\n\n"
        "If you need to change or cancel, please contact the practice.\n"
    )
    html = f"""
    <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background:#f9fafb;padding:24px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="600" style="max-width:600px;background:#ffffff;border-radius:16px;overflow:hidden;">
            <tr>
              <td style="padding:22px 22px 10px 22px;">
                <div style="font-family:Arial,Helvetica,sans-serif;">
                  <div style="font-size:12px;letter-spacing:0.08em;text-transform:uppercase;color:#6b7280;">NextHealth</div>
                  <div style="margin-top:8px;font-size:22px;font-weight:700;color:#111827;">Booking confirmed</div>
                  <div style="margin-top:6px;font-size:14px;color:#4b5563;">{practice_name}</div>
                </div>
              </td>
            </tr>
            <tr>
              <td style="padding:8px 22px 4px 22px;">
                <div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.5;color:#374151;">
                  Hi {patient_name}, your appointment is confirmed.
                </div>
              </td>
            </tr>
            <tr>
              <td style="padding:12px 22px 22px 22px;">
                <div style="font-family:Arial,Helvetica,sans-serif;background:#f0fdfa;border:1px solid #ccfbf1;border-radius:12px;padding:16px;color:#134e4a;">
                  <div style="font-size:16px;font-weight:700;">{appointment_type}</div>
                  <div style="margin-top:6px;font-size:14px;">{when}</div>
                  <div style="margin-top:4px;font-size:14px;">with {provider_name}</div>
                  <div style="margin-top:8px;font-size:13px;color:#0f766e;">{where}</div>
                </div>
              </td>
            </tr>
            <tr>
              <td style="padding:0 22px 22px 22px;">
                <div style="font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:1.4;color:#6b7280;text-align:center;">
                  If you need to change or cancel, contact the practice directly.
                </div>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
    """.strip()
    send_email(to=to, subject=subject, html=html, text=text)


def send_booking_cancelled(
    *,
    to: str,
    patient_name: str,
    practice_name: str,
    location_name: str,
    location_address: str,
    appointment_type: str,
    provider_name: str,
    when: str,
) -> None:
    """Email the patient that their appointment was cancelled."""
    subject = f"Your appointment was cancelled — {practice_name}"
    where = location_name if not location_address else f"{location_name}, {location_address}"
    text = (
        f"Hi {patient_name},\n\n"
        f"Your appointment with {practice_name} has been cancelled.\n\n"
        f"{appointment_type} with {provider_name}\n"
        f"{when}\n"
        f"{where}\n\n"
        "If you did not request this or want to reschedule, please contact the practice.\n"
    )
    html = f"""
    <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background:#f9fafb;padding:24px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="600" style="max-width:600px;background:#ffffff;border-radius:16px;overflow:hidden;">
            <tr>
              <td style="padding:22px 22px 10px 22px;">
                <div style="font-family:Arial,Helvetica,sans-serif;">
                  <div style="font-size:12px;letter-spacing:0.08em;text-transform:uppercase;color:#6b7280;">NextHealth</div>
                  <div style="margin-top:8px;font-size:22px;font-weight:700;color:#111827;">Appointment cancelled</div>
                  <div style="margin-top:6px;font-size:14px;color:#4b5563;">{practice_name}</div>
                </div>
              </td>
            </tr>
            <tr>
              <td style="padding:8px 22px 4px 22px;">
                <div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.5;color:#374151;">
                  Hi {patient_name}, your appointment has been cancelled.
                </div>
              </td>
            </tr>
            <tr>
              <td style="padding:12px 22px 22px 22px;">
                <div style="font-family:Arial,Helvetica,sans-serif;background:#fef2f2;border:1px solid #fecaca;border-radius:12px;padding:16px;color:#7f1d1d;">
                  <div style="font-size:16px;font-weight:700;">{appointment_type}</div>
                  <div style="margin-top:6px;font-size:14px;">{when}</div>
                  <div style="margin-top:4px;font-size:14px;">with {provider_name}</div>
                  <div style="margin-top:8px;font-size:13px;color:#991b1b;">{where}</div>
                </div>
              </td>
            </tr>
            <tr>
              <td style="padding:0 22px 22px 22px;">
                <div style="font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:1.4;color:#6b7280;text-align:center;">
                  If you want to reschedule, contact the practice directly.
                </div>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
    """.strip()
    send_email(to=to, subject=subject, html=html, text=text)

