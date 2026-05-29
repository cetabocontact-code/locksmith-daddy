"""Best-effort SMS via Twilio (Layer 2 anti-abuse).

If Twilio creds aren't configured, all sends are no-ops that log a warning.
The caller can detect "we didn't actually send" via the return value but
should treat failure as non-fatal for the user flow (UX simply skips the
phone-verification step in that case).

Env vars: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER.
"""

from __future__ import annotations

import logging

import httpx

from lbt1 import config

log = logging.getLogger(__name__)

TWILIO_API = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


def is_enabled() -> bool:
    return bool(
        config.TWILIO_ACCOUNT_SID
        and config.TWILIO_AUTH_TOKEN
        and config.TWILIO_FROM_NUMBER
    )


def send_verification_code(to_phone: str, code: str) -> bool:
    """Returns True if actually sent. Never raises."""
    if not is_enabled():
        log.info("SMS not configured — skipping send to %s (code %s)", to_phone, code)
        return False
    if not to_phone:
        return False

    body = (
        f"Locksmith Daddy verification code: {code}\n\n"
        "Don't share this with anyone. The code expires in 10 minutes."
    )
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                TWILIO_API.format(sid=config.TWILIO_ACCOUNT_SID),
                auth=(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN),
                data={
                    "From": config.TWILIO_FROM_NUMBER,
                    "To": to_phone,
                    "Body": body,
                },
            )
        if 200 <= resp.status_code < 300:
            log.info("SMS sent to %s", to_phone)
            return True
        log.warning("Twilio HTTP %d for %s: %s", resp.status_code, to_phone, resp.text[:200])
        return False
    except Exception as exc:  # noqa: BLE001 — never raise
        log.warning("SMS send failed to %s: %s", to_phone, exc)
        return False
