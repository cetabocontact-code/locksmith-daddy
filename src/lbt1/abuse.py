"""Anti-abuse helpers (Layer 1).

- Disposable email blocklist
- IP-based signup rate limit
- State license + phone uniqueness (enforced at DB layer via UNIQUE indexes)
- Browser fingerprint logging (stored for admin review)
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import Request

from lbt1 import db
from lbt1.disposable_emails import is_disposable

# Defaults — tune later if abuse patterns emerge.
SIGNUP_RATE_LIMIT_WINDOW_DAYS = 7
SIGNUP_RATE_LIMIT_COUNT = 3


def client_ip(request: Request) -> str:
    """Best-effort client IP. Honors X-Forwarded-For when behind a proxy
    (Fly.io sets fly-client-ip header)."""
    h = request.headers
    forwarded = h.get("fly-client-ip") or h.get("x-forwarded-for") or ""
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "0.0.0.0"


def browser_fingerprint(request: Request) -> str:
    """Stable hash of UA + Accept-Language + a few other headers. Not a unique
    identifier (real fingerprinting needs client-side JS), but flags obvious
    abusers who use the same browser config repeatedly."""
    ua = request.headers.get("user-agent", "")
    al = request.headers.get("accept-language", "")
    ae = request.headers.get("accept-encoding", "")
    blob = f"{ua}|{al}|{ae}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


class AbuseError(Exception):
    """Raised when an anti-abuse rule blocks an operation. The message is
    user-visible — keep it polite + actionable."""


def check_email_not_disposable(email: str) -> None:
    if is_disposable(email):
        raise AbuseError(
            "This email provider isn't supported. Please sign up with a "
            "permanent email address (Gmail, Outlook, your business email, etc.)."
        )


def check_ip_signup_rate(ip: str) -> None:
    """Block if this IP has already attempted N signups in the window."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=SIGNUP_RATE_LIMIT_WINDOW_DAYS)
    ).isoformat(timespec="seconds")
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM signup_attempts WHERE ip = ? AND attempted_at >= ?",
            (ip, cutoff),
        ).fetchone()
        n = int(row["n"] or 0)
    if n >= SIGNUP_RATE_LIMIT_COUNT:
        raise AbuseError(
            f"Too many signup attempts from this network in the last "
            f"{SIGNUP_RATE_LIMIT_WINDOW_DAYS} days. Please try again later or "
            "contact support if you believe this is in error."
        )


def count_anonymous_lookups_last_hour(ip: str) -> int:
    """Anti-abuse for the public paywall flow: count how many anonymous
    lookup jobs this IP has started in the last hour. Caller can throttle.

    Different from check_ip_signup_rate — that one tracks signups, this one
    tracks paywall lookup creates. Both run in parallel."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=1)
    ).isoformat(timespec="seconds")
    with db.get_db() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM lookup_jobs
            WHERE source_ip = ? AND created_at >= ?
            """,
            (ip, cutoff),
        ).fetchone()
        return int(row["n"] or 0)


def check_state_lic_not_taken(state_lic: str) -> None:
    """State lic numbers are real-world unique. Reject duplicates."""
    if not state_lic:
        return
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE state_lic = ?", (state_lic.strip(),)
        ).fetchone()
    if row is not None:
        raise AbuseError(
            "This state license number is already registered. "
            "If you've forgotten your password, use the Reset Password link."
        )


def check_phone_not_taken(phone: str) -> None:
    if not phone:
        return
    normalized = "".join(c for c in phone if c.isdigit())
    if not normalized:
        return
    with db.get_db() as conn:
        # Match against the normalized digits in case formatting differs
        row = conn.execute(
            "SELECT id FROM users WHERE REPLACE(REPLACE(REPLACE(REPLACE(phone, '-', ''), ' ', ''), '(', ''), ')', '') = ?",
            (normalized,),
        ).fetchone()
    if row is not None:
        raise AbuseError(
            "This phone number is already registered. "
            "If you've forgotten your password, use the Reset Password link."
        )


def log_signup_attempt(*, ip: str, user_agent: str, email: str, success: bool) -> None:
    """Record every signup attempt for rate-limit accounting and audit."""
    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO signup_attempts(ip, user_agent, email, success, attempted_at)
            VALUES(?, ?, ?, ?, ?)
            """,
            (
                ip,
                user_agent[:500] if user_agent else None,
                email[:255] if email else None,
                1 if success else 0,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )


def run_layer1_checks(*, email: str, state_lic: str, phone: str, ip: str) -> None:
    """All Layer-1 anti-abuse checks. Raises AbuseError on the first failure."""
    check_email_not_disposable(email)
    check_ip_signup_rate(ip)
    check_state_lic_not_taken(state_lic)
    check_phone_not_taken(phone)
