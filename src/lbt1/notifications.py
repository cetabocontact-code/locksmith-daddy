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


def send(to: str, subject: str, body: str) -> bool:
    """Send a plain-text email. Returns True on success, False otherwise.
    Never raises."""
    if not config.EMAIL_ENABLED:
        log.info("Email not configured — skipping send to %s (subject=%r)", to, subject)
        return False

    if not to or "@" not in to:
        log.info("Skipping email to malformed address %r", to)
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config.EMAIL_FROM
    msg["To"] = to
    msg.set_content(body)

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as smtp:
            smtp.ehlo()
            if config.SMTP_USE_TLS:
                smtp.starttls()
                smtp.ehlo()
            smtp.login(config.SMTP_USER, config.SMTP_PASS)
            smtp.send_message(msg)
        log.info("Email sent to %s (subject=%r)", to, subject)
        return True
    except Exception as exc:
        log.warning("Email send failed to %s: %s", to, exc)
        return False


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
