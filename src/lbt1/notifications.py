"""Best-effort email notifications.

Design contract: NOTHING in this module is allowed to block the user flow.
SMTP outages, fake addresses, bad templates — all caught and logged. The
return value (bool) tells the caller whether the email was sent, but the
caller should never branch on it for user-facing logic.

Configure via env vars (see config.py): SMTP_HOST, SMTP_PORT, SMTP_USER,
SMTP_PASS, SMTP_USE_TLS, EMAIL_FROM. If any are missing, the sender is a
no-op and logs "email not configured".
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from lbt1 import config

log = logging.getLogger(__name__)


def _resolve_from_address() -> str:
    """Pick a From: header that the SMTP host will actually accept.

    The most common deliverability failure on shared SMTP hosts (Gmail
    in particular) is a From-address mismatch: SMTP_USER authenticates
    as alice@gmail.com but the message header says noreply@example.com,
    so Gmail rejects with "Sender address rejected: not owned by user".

    Rule:
      - If EMAIL_FROM's email part matches SMTP_USER → use EMAIL_FROM as-is
        (keeps friendly "Locksmith Daddy <…>" display name).
      - Otherwise, if SMTP_HOST is Gmail or similar enforced relays →
        replace the email part with SMTP_USER but preserve display name.
      - For other relays (SendGrid, Mailgun, Resend) the original
        EMAIL_FROM is preserved.
    """
    raw = config.EMAIL_FROM or ""
    user = (config.SMTP_USER or "").strip().lower()
    host = (config.SMTP_HOST or "").strip().lower()
    enforced_hosts = {
        "smtp.gmail.com", "smtp.googlemail.com",
        "smtp.office365.com", "smtp-mail.outlook.com",
        "smtp.mail.yahoo.com", "smtp.zoho.com",
    }
    if "<" in raw and ">" in raw:
        display = raw.split("<", 1)[0].strip()
        email_part = raw.split("<", 1)[1].rstrip(">").strip().lower()
    else:
        display = ""
        email_part = raw.strip().lower()
    if user and email_part and email_part == user:
        return raw  # already matches authenticated user
    if user and host in enforced_hosts:
        display = display or "Locksmith Daddy"
        return f"{display} <{user}>"
    return raw


def send(to: str, subject: str, body: str) -> bool:
    """Send a plain-text email. Returns True on success, False otherwise.
    Never raises."""
    return _send_with_report(to, subject, body)[0]


def _send_with_report(to: str, subject: str, body: str) -> tuple[bool, str]:
    """Internal: returns (ok, diagnostic_msg). diagnostic_msg is empty on
    success or carries the SMTP error / skip reason on failure. Used by
    the test-email admin endpoint to surface SMTP issues to operators."""
    if not config.EMAIL_ENABLED:
        msg = (
            f"EMAIL_ENABLED is False. "
            f"SMTP_HOST={config.SMTP_HOST!r}, "
            f"SMTP_USER={'set' if config.SMTP_USER else 'EMPTY'}, "
            f"SMTP_PASS={'set' if config.SMTP_PASS else 'EMPTY'}. "
            f"All three must be present."
        )
        log.info("Email skipped: %s", msg)
        return False, msg

    if not to or "@" not in to:
        return False, f"Recipient {to!r} is malformed"

    from_header = _resolve_from_address()
    msg_obj = EmailMessage()
    msg_obj["Subject"] = subject
    msg_obj["From"] = from_header
    msg_obj["To"] = to
    msg_obj.set_content(body)

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as smtp:
            smtp.ehlo()
            if config.SMTP_USE_TLS:
                smtp.starttls()
                smtp.ehlo()
            smtp.login(config.SMTP_USER, config.SMTP_PASS)
            smtp.send_message(msg_obj)
        log.info(
            "Email sent: to=%s subject=%r from=%s host=%s",
            to, subject, from_header, config.SMTP_HOST,
        )
        return True, ""
    except smtplib.SMTPAuthenticationError as exc:
        diag = (
            f"SMTP auth failed (host={config.SMTP_HOST}, "
            f"user={config.SMTP_USER}): {exc.smtp_code} {exc.smtp_error!r}. "
            "For Gmail: enable 2FA + generate an App Password and use that as SMTP_PASS."
        )
        log.warning(diag)
        return False, diag
    except smtplib.SMTPSenderRefused as exc:
        diag = (
            f"SMTP rejected the From address {from_header!r}: "
            f"{exc.smtp_code} {exc.smtp_error!r}. "
            "Most SMTP hosts require the From email to match SMTP_USER. "
            "Set EMAIL_FROM to use {SMTP_USER} or use a relay that supports custom senders."
        )
        log.warning(diag)
        return False, diag
    except smtplib.SMTPRecipientsRefused as exc:
        diag = f"SMTP rejected the recipient(s): {exc.recipients!r}"
        log.warning(diag)
        return False, diag
    except smtplib.SMTPException as exc:
        diag = f"SMTP error class={type(exc).__name__} args={exc.args!r}"
        log.warning(diag)
        return False, diag
    except Exception as exc:  # noqa: BLE001
        diag = f"Unexpected send error class={type(exc).__name__} args={exc.args!r}"
        log.warning(diag)
        return False, diag


def email_diagnostic() -> dict:
    """Snapshot of the current email config that's safe to surface to
    operators on /admin/email-status. No secrets returned — just which
    fields are populated and what From-header we'd use."""
    return {
        "enabled": config.EMAIL_ENABLED,
        "smtp_host": config.SMTP_HOST or None,
        "smtp_port": config.SMTP_PORT,
        "smtp_use_tls": config.SMTP_USE_TLS,
        "smtp_user_set": bool(config.SMTP_USER),
        "smtp_pass_set": bool(config.SMTP_PASS),
        "smtp_user_value": config.SMTP_USER,  # not a secret; useful for debugging
        "email_from_configured": config.EMAIL_FROM,
        "email_from_effective": _resolve_from_address(),
    }


def send_signup_welcome(*, to: str, full_name: str) -> bool:
    body = (
        f"Hi {full_name or 'there'},\n\n"
        "Welcome to the Locksmith Daddy.\n\n"
        "Your account is active. Sign in at " + config.BASE_URL + " to look up "
        "OEM key part numbers by VIN.\n\n"
        "This tool is for certified locksmiths only.\n\n"
        "— Locksmith Daddy\n"
    )
    return send(to, "Welcome to Locksmith Daddy", body)


def send_signup_welcome_with_verify(
    *, to: str, full_name: str, verify_url: str,
    trial_days: int = 30, trial_lookups: int = 3,
) -> bool:
    """Welcome + email verification link in one message. Sent right after signup."""
    body = (
        f"Hi {full_name or 'there'},\n\n"
        "Welcome to the Locksmith Daddy.\n\n"
        f"Your free trial is active: {trial_days} days or {trial_lookups} VIN "
        "lookups, whichever comes first.\n\n"
        "Please verify your email to start using the tool:\n"
        f"{verify_url}\n\n"
        "If you didn't sign up, just ignore this email — the account stays inactive.\n\n"
        "— Locksmith Daddy\n"
    )
    return send(to, "Verify your email — Locksmith Daddy", body)


def send_email_verify_resend(*, to: str, full_name: str, verify_url: str) -> bool:
    body = (
        f"Hi {full_name or 'there'},\n\n"
        "Here's a fresh email verification link:\n"
        f"{verify_url}\n\n"
        "Link is valid for 48 hours.\n\n"
        "— Locksmith Daddy\n"
    )
    return send(to, "Verify your email — Locksmith Daddy", body)


def send_trial_warning(*, to: str, full_name: str, days_left: int, lookups_left: int) -> bool:
    """Mid-trial heads-up — sent on day 28 (2 days left) by a cron, or
    when lookups_remaining hits 1."""
    body = (
        f"Hi {full_name or 'there'},\n\n"
        f"Heads up: your Locksmith Daddy free trial has {days_left} day(s) "
        f"and {lookups_left} VIN lookup(s) left.\n\n"
        "To keep going after the trial ends, subscribe at:\n"
        f"{config.BASE_URL}/subscribe\n\n"
        "— Locksmith Daddy\n"
    )
    return send(to, "Your Locksmith Daddy trial is ending soon", body)


def send_trial_expired(*, to: str, full_name: str, reason: str = "time") -> bool:
    """Notify the user their trial ended. `reason` is 'time' or 'lookups'."""
    if reason == "lookups":
        opener = "You just used the last lookup in your free trial."
    else:
        opener = "Your 30-day free trial has ended."
    body = (
        f"Hi {full_name or 'there'},\n\n"
        f"{opener}\n\n"
        "To keep looking up OEM key part numbers by VIN, subscribe at:\n"
        f"{config.BASE_URL}/subscribe\n\n"
        "Pro is $19.99/month for 50 lookups. Shop and unlimited tiers are "
        "available for busy teams.\n\n"
        "Questions? Reply to this email.\n\n"
        "— Locksmith Daddy\n"
    )
    return send(to, "Your Locksmith Daddy trial has ended", body)


def send_password_reset(*, to: str, reset_url: str) -> bool:
    body = (
        "Someone (you, we hope) asked to reset the password on this Locksmith "
        "Brain account.\n\n"
        f"Reset link (valid 30 minutes):\n{reset_url}\n\n"
        "If this wasn't you, you can ignore this email — your password stays "
        "the same.\n\n"
        "— Locksmith Daddy\n"
    )
    return send(to, "Reset your Locksmith Daddy password", body)


def send_newsletter_confirmation(*, to: str, full_name: str) -> bool:
    body = (
        f"Hi {full_name or 'there'},\n\n"
        "You're on the Locksmith Daddy newsletter list. We'll send a short "
        "update whenever a new tool or major improvement ships — no spam, "
        "no daily emails.\n\n"
        "— Locksmith Daddy\n"
    )
    return send(to, "Subscribed to Locksmith Daddy updates", body)


def send_purchase_receipt(
    *, to: str, vehicle_label: str, primary_pn: str,
    dealer_url: str, alt_pns: list[str] | None,
    amount_cents: int, kind: str, result_url: str,
    stripe_session_id: str,
) -> bool:
    """Email the customer their purchase receipt + the dealer-verified PN.

    Sent immediately after Stripe webhook fires `checkout.session.completed`
    and we've marked the job paid. Includes the PN + dealer URL so they
    have a permanent record outside the web app, plus a link back to the
    /result page where they can re-access it.
    """
    dollars = f"${amount_cents / 100:.2f}"
    label = (
        "single VIN unlock"
        if kind == "single"
        else "10-pack of VIN unlocks (1 used now, 9 credits in your account)"
        if kind == "ten"
        else "VIN unlock"
    )
    alt_lines = ""
    if alt_pns:
        alt_lines = (
            "\nAlternate part numbers the dealer also lists for this vehicle:\n"
            + "\n".join(f"  - {p}" for p in alt_pns) + "\n"
        )
    body = (
        f"Thanks for your purchase.\n\n"
        f"VEHICLE: {vehicle_label}\n"
        f"DEALER-VERIFIED OEM PART NUMBER: {primary_pn}\n"
        f"{alt_lines}"
        f"DEALER PROOF-OF-FITMENT URL: {dealer_url}\n\n"
        f"RECEIPT\n"
        f"  Item:           {label}\n"
        f"  Charge:         {dollars} USD\n"
        f"  Stripe session: {stripe_session_id}\n\n"
        f"You can re-access this result any time at:\n"
        f"  {result_url}\n\n"
        f"If you create a free account (no license required), this VIN "
        f"will appear in your dashboard automatically. Sign up at:\n"
        f"  {result_url.split('/result/')[0]}/signup\n\n"
        f"Questions? Reply to this email or contact contact@locksmithdaddy.us.\n\n"
        f"— Locksmith Daddy\n"
        f"   a Cetabo LLC venture\n"
    )
    return send(
        to,
        f"Your Locksmith Daddy result: {primary_pn} for {vehicle_label}",
        body,
    )


def send_enterprise_lead_notification(
    *, company: str, contact_name: str, contact_email: str, phone: str,
    role: str, monthly_volume: str, notes: str,
) -> bool:
    """Notify the ops inbox (config.OPS_EMAIL) that an enterprise lead just
    submitted the /enterprise contact form."""
    body = (
        "New enterprise / reseller lead from /enterprise:\n\n"
        f"Company:           {company}\n"
        f"Contact name:      {contact_name}\n"
        f"Contact email:     {contact_email}\n"
        f"Phone:             {phone or '(not provided)'}\n"
        f"Role / type:       {role}\n"
        f"Monthly volume:    {monthly_volume}\n\n"
        f"Notes:\n{notes or '(none)'}\n\n"
        "— Locksmith Daddy automated form\n"
    )
    return send(
        config.OPS_EMAIL,
        f"[LD Enterprise] New lead: {company} ({monthly_volume})",
        body,
    )
