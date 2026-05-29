"""Password hashing + signup/signin business rules + FastAPI dependency
that resolves the current user from the session cookie.

Fake emails are intentionally permitted — the requirement is "fake data or
wrong email sign up should allow accessing the tool". The only validation is
basic format (so the DB stores something sensible), not deliverability.
"""

from __future__ import annotations

import re

import bcrypt
from fastapi import Cookie, HTTPException, Request, status

from lbt1 import config, db

# Loose email regex — allows obviously bad ones (we WANT fake emails to pass).
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

# bcrypt has a 72-byte input limit. Truncating is the standard mitigation.
_BCRYPT_MAX_BYTES = 72


class AuthError(Exception):
    pass


def _to_bytes(plain: str) -> bytes:
    encoded = plain.encode("utf-8")
    return encoded[:_BCRYPT_MAX_BYTES] if len(encoded) > _BCRYPT_MAX_BYTES else encoded


def hash_password(plain: str) -> str:
    hashed = bcrypt.hashpw(_to_bytes(plain), bcrypt.gensalt(rounds=12))
    return hashed.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_to_bytes(plain), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def normalize_email(email: str) -> str:
    return email.strip().lower()


def signup(
    *,
    email: str,
    password: str,
    full_name: str,
    phone: str,
    state_lic: str,
    locksmith_lic: str | None,
    newsletter_opt_in: bool,
    # New: consent + anti-abuse context
    privacy_consent: bool = False,
    marketing_consent: bool = False,
    signup_ip: str | None = None,
    signup_user_agent: str | None = None,
    signup_fingerprint: str | None = None,
) -> tuple[int, str]:
    """Create a user and return (user_id, session_token).

    Applies Layer-1 anti-abuse checks (disposable-email blocklist, IP rate
    limit, state-lic + phone uniqueness) BEFORE creating the user. Raises
    AuthError on validation OR AbuseError on anti-abuse block — both are
    safe to surface verbatim to the user.

    Trial mechanics: every new user gets a {TRIAL_DAYS}-day, {TRIAL_LOOKUPS}-
    lookup trial by default (configurable via env vars).
    """
    from lbt1 import abuse, config

    email = normalize_email(email)
    full_name = (full_name or "").strip()
    phone = (phone or "").strip()
    state_lic = (state_lic or "").strip()
    password = password or ""

    if not _EMAIL_RE.match(email):
        raise AuthError("Email looks malformed. Even a fake address needs an @ and a dot.")
    if len(password) < 8:
        raise AuthError("Password must be at least 8 characters.")
    if not full_name:
        raise AuthError("Full name is required.")
    if not phone:
        raise AuthError("Phone number is required.")
    if not state_lic:
        raise AuthError("State license number is required.")
    if not privacy_consent:
        raise AuthError(
            "You must agree to our privacy notice (we store your contact "
            "info to provide the service) before creating an account."
        )

    if db.get_user_by_email(email) is not None:
        raise AuthError("An account with this email already exists. Sign in instead.")

    # Layer-1 anti-abuse: disposable emails, IP rate limit, state-lic + phone uniqueness.
    # AbuseError messages are user-facing and safe to surface.
    abuse.run_layer1_checks(
        email=email, state_lic=state_lic, phone=phone, ip=signup_ip or "0.0.0.0"
    )

    user_id = db.create_user(
        email=email,
        password_hash=hash_password(password),
        full_name=full_name,
        phone=phone,
        state_lic=state_lic,
        locksmith_lic=locksmith_lic,
        newsletter_opt_in=newsletter_opt_in or marketing_consent,
        trial_days=config.TRIAL_DAYS,
        trial_lookups=config.TRIAL_LOOKUPS,
        marketing_consent=marketing_consent,
        signup_ip=signup_ip,
        signup_user_agent=signup_user_agent,
        signup_fingerprint=signup_fingerprint,
    )
    token = db.create_session(user_id)
    return user_id, token


def signin(*, email: str, password: str) -> tuple[int, str]:
    """Return (user_id, session_token) on success, raise AuthError otherwise."""
    email = normalize_email(email)
    row = db.get_user_by_email(email)
    if row is None or not verify_password(password, row["password_hash"]):
        # Single message for both wrong-email and wrong-password — don't leak
        # which emails are registered.
        raise AuthError("Email or password is incorrect.")
    token = db.create_session(int(row["id"]))
    db.touch_last_seen(int(row["id"]))
    return int(row["id"]), token


def signout(token: str | None) -> None:
    if token:
        db.delete_session(token)


def current_user_or_none(request: Request) -> dict | None:
    """Resolve the user from the session cookie. Returns None for guests."""
    token = request.cookies.get(config.SESSION_COOKIE_NAME)
    if not token:
        return None
    row = db.get_user_by_session(token)
    if row is None:
        return None
    return _row_to_user_dict(row)


def require_user(request: Request) -> dict:
    """FastAPI dependency — 401s guests, 403s banned users. Use on protected endpoints."""
    user = current_user_or_none(request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in required.",
        )
    # Banned check — every protected endpoint enforces it.
    if user.get("subscription_tier") == "banned":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account suspended. Contact support if you think this is an error.",
        )
    return user


def _row_to_user_dict(row) -> dict:
    keys = row.keys()
    def g(k, default=None):
        return row[k] if k in keys else default
    return {
        "id": int(row["id"]),
        "email": row["email"],
        "full_name": row["full_name"],
        "phone": row["phone"],
        "state_lic": row["state_lic"],
        "locksmith_lic": row["locksmith_lic"],
        "newsletter_opt_in": bool(row["newsletter_opt_in"]),
        "created_at": row["created_at"],
        "last_seen_at": row["last_seen_at"],
        "total_lookup_seconds": int(row["total_lookup_seconds"]),
        "total_lookups": int(row["total_lookups"]),
        # New (post-migration) fields — tolerant of older DB rows.
        "subscription_tier": g("subscription_tier") or "trial",
        "trial_started_at": g("trial_started_at"),
        "trial_expires_at": g("trial_expires_at"),
        "trial_lookups_remaining": int(g("trial_lookups_remaining") or 0),
        "email_verified_at": g("email_verified_at"),
        "phone_verified_at": g("phone_verified_at"),
        "marketing_consent": bool(g("marketing_consent")),
        "stripe_customer_id": g("stripe_customer_id"),
        "stripe_subscription_id": g("stripe_subscription_id"),
        "card_brand": g("card_brand"),
        "card_last4": g("card_last4"),
        "founder_signup_number": g("founder_signup_number"),
        "banned_at": g("banned_at"),
        "banned_reason": g("banned_reason"),
    }
