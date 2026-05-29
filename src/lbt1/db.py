"""SQLite layer. One file at data/lbt1.db. Migrations are inline DDL — the
schema is small enough that a real migration tool would be overkill for v0.

Tables:
    users         — accounts (signup form data + usage counters)
    sessions      — cookie-token → user_id
    lookups       — every VIN lookup, kept VIN_RETENTION_DAYS days
    part_reports  — locksmith-flagged "this PN looks wrong" reports

Notes on auth:
    Email is NOT verified. Fake addresses are allowed — best-effort emails go
    out if SMTP is configured, but signup never blocks on email validity.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from lbt1 import config

TABLES_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    state_lic TEXT NOT NULL,
    locksmith_lic TEXT,
    newsletter_opt_in INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_seen_at TEXT,
    total_lookup_seconds INTEGER NOT NULL DEFAULT 0,
    total_lookups INTEGER NOT NULL DEFAULT 0,
    -- Trial mechanics
    subscription_tier TEXT NOT NULL DEFAULT 'trial',
    trial_started_at TEXT,
    trial_expires_at TEXT,
    trial_lookups_remaining INTEGER NOT NULL DEFAULT 3,
    -- Verification
    email_verified_at TEXT,
    phone_verified_at TEXT,
    -- Consent + marketing
    privacy_consent_at TEXT NOT NULL DEFAULT '',
    marketing_consent INTEGER NOT NULL DEFAULT 0,
    marketing_consent_at TEXT,
    marketing_unsubscribed_at TEXT,
    -- Anti-abuse signals
    signup_ip TEXT,
    signup_user_agent TEXT,
    signup_fingerprint TEXT,
    -- Payment (Stripe)
    stripe_customer_id TEXT,
    stripe_payment_method_id TEXT,
    card_brand TEXT,
    card_last4 TEXT
);

-- Per-IP signup rate limit (Layer 1)
CREATE TABLE IF NOT EXISTS signup_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip TEXT NOT NULL,
    user_agent TEXT,
    email TEXT,
    success INTEGER NOT NULL DEFAULT 0,
    attempted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signup_attempts_ip ON signup_attempts(ip, attempted_at);

-- Email verification (Layer 2)
CREATE TABLE IF NOT EXISTS email_verification_tokens (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_email_verif_user ON email_verification_tokens(user_id);

-- Phone verification codes (Layer 2)
CREATE TABLE IF NOT EXISTS phone_verification_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_phone_verif_user ON phone_verification_codes(user_id, sent_at DESC);

-- Marketing subscribers (denormalized view for export to email lists)
CREATE TABLE IF NOT EXISTS marketing_subscribers (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    full_name TEXT,
    phone TEXT,
    state_lic TEXT,
    subscribed_at TEXT NOT NULL,
    unsubscribed_at TEXT,
    tags TEXT DEFAULT 'subscribed'
);
CREATE INDEX IF NOT EXISTS idx_marketing_subs_active ON marketing_subscribers(unsubscribed_at) WHERE unsubscribed_at IS NULL;

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT
);

CREATE TABLE IF NOT EXISTS lookups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    vin TEXT NOT NULL,
    created_at TEXT NOT NULL,
    duration_seconds INTEGER NOT NULL,
    dealer_verification_status TEXT NOT NULL,
    primary_pn TEXT,
    confidence_score REAL NOT NULL,
    confidence_label TEXT NOT NULL,
    result_json TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lookups_user ON lookups(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_lookups_expires ON lookups(expires_at);

CREATE TABLE IF NOT EXISTS part_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lookup_id INTEGER REFERENCES lookups(id) ON DELETE SET NULL,
    vin TEXT NOT NULL,
    part_number TEXT NOT NULL,
    issue TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_reports_user ON part_reports(user_id, created_at DESC);
"""

# Indexes that depend on user-table columns added by the migration. These run
# AFTER _migrate_users_columns to avoid "no such column" errors on upgrade.
USER_INDEXES_SCHEMA = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_state_lic ON users(state_lic) WHERE state_lic != '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone ON users(phone) WHERE phone != '';
CREATE INDEX IF NOT EXISTS idx_users_marketing ON users(marketing_consent) WHERE marketing_consent = 1;
"""


def init_db() -> None:
    """Create the schema and run lightweight in-place migrations.

    Idempotent — safe to call on every app start. SQLite ALTER TABLE only
    supports ADD COLUMN, so for upgrades we ADD any column that's missing.
    """
    with _connect() as conn:
        # 1. Create tables (no-op if they exist with old schema)
        conn.executescript(TABLES_SCHEMA)
        # 2. ADD any new columns to the users table (upgrade-in-place)
        _migrate_users_columns(conn)
        # 3. Create indexes that reference post-migration columns
        conn.executescript(USER_INDEXES_SCHEMA)
        conn.commit()


# Columns we ADD-if-missing for upgrade-in-place from earlier schemas.
_USERS_NEW_COLUMNS: list[tuple[str, str]] = [
    ("subscription_tier", "TEXT NOT NULL DEFAULT 'trial'"),
    ("trial_started_at", "TEXT"),
    ("trial_expires_at", "TEXT"),
    ("trial_lookups_remaining", "INTEGER NOT NULL DEFAULT 10"),
    ("email_verified_at", "TEXT"),
    ("phone_verified_at", "TEXT"),
    ("privacy_consent_at", "TEXT NOT NULL DEFAULT ''"),
    ("marketing_consent", "INTEGER NOT NULL DEFAULT 0"),
    ("marketing_consent_at", "TEXT"),
    ("marketing_unsubscribed_at", "TEXT"),
    ("signup_ip", "TEXT"),
    ("signup_user_agent", "TEXT"),
    ("signup_fingerprint", "TEXT"),
    ("stripe_customer_id", "TEXT"),
    ("stripe_subscription_id", "TEXT"),
    ("stripe_payment_method_id", "TEXT"),
    ("card_brand", "TEXT"),
    ("card_last4", "TEXT"),
    # Founder program tracking. NULL for non-founders, 1..N for the first N signups.
    ("founder_signup_number", "INTEGER"),
    ("banned_at", "TEXT"),
    ("banned_reason", "TEXT"),
]


def _migrate_users_columns(conn) -> None:
    """Add any user-table columns that don't exist yet, for upgrade-in-place.
    Also backfill trial fields for any existing pre-migration users."""
    from datetime import datetime, timedelta, timezone
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    columns_added = False
    for col, spec in _USERS_NEW_COLUMNS:
        if col in existing:
            continue
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {spec}")
            columns_added = True
        except Exception:  # pragma: no cover — best effort
            pass

    # Backfill any users with NULL trial_expires_at — give them 30 days from now.
    try:
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(days=30)).isoformat(timespec="seconds")
        conn.execute(
            "UPDATE users SET trial_started_at = ?, trial_expires_at = ? "
            "WHERE trial_expires_at IS NULL OR trial_expires_at = ''",
            (now.isoformat(timespec="seconds"), expires),
        )
    except Exception:
        pass


def _connect() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.DB_PATH), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency / generic context manager. Auto-closes connection."""
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ─── User helpers ────────────────────────────────────────────────────────────


def create_user(
    *,
    email: str,
    password_hash: str,
    full_name: str,
    phone: str,
    state_lic: str,
    locksmith_lic: str | None,
    newsletter_opt_in: bool,
    # New: trial + consent + abuse fields
    trial_days: int = 36500,
    trial_lookups: int = 10,
    privacy_consent_at: str | None = None,
    marketing_consent: bool = False,
    signup_ip: str | None = None,
    signup_user_agent: str | None = None,
    signup_fingerprint: str | None = None,
) -> int:
    from datetime import datetime, timedelta, timezone
    now = utcnow_iso()
    trial_expires = (
        datetime.now(timezone.utc) + timedelta(days=trial_days)
    ).isoformat(timespec="seconds")

    # Determine if this signup is a founder (one of the first N).
    from lbt1 import config
    with get_db() as count_conn:
        count_row = count_conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE founder_signup_number IS NOT NULL"
        ).fetchone()
        existing_founders = int(count_row["n"] or 0) if count_row else 0
    founder_number = existing_founders + 1 if existing_founders < config.FOUNDER_SLOTS else None

    with get_db() as conn:
        conn.execute("BEGIN")
        try:
            cur = conn.execute(
                """
                INSERT INTO users(
                    email, password_hash, full_name, phone, state_lic, locksmith_lic,
                    newsletter_opt_in, created_at,
                    subscription_tier, trial_started_at, trial_expires_at,
                    trial_lookups_remaining,
                    privacy_consent_at, marketing_consent, marketing_consent_at,
                    signup_ip, signup_user_agent, signup_fingerprint,
                    founder_signup_number
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    email.strip(),
                    password_hash,
                    full_name.strip(),
                    phone.strip(),
                    state_lic.strip(),
                    (locksmith_lic or "").strip() or None,
                    1 if newsletter_opt_in else 0,
                    now,
                    "trial",
                    now,
                    trial_expires,
                    trial_lookups,
                    privacy_consent_at or now,
                    1 if marketing_consent else 0,
                    now if marketing_consent else None,
                    signup_ip,
                    (signup_user_agent or "")[:500] or None,
                    signup_fingerprint,
                    founder_number,
                ),
            )
            user_id = int(cur.lastrowid)  # type: ignore[arg-type]

            # If the user opted in to marketing, add them to the
            # marketing_subscribers table (tag = "subscribed").
            if marketing_consent:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO marketing_subscribers(
                        user_id, email, full_name, phone, state_lic,
                        subscribed_at, tags
                    ) VALUES(?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        email.strip(),
                        full_name.strip(),
                        phone.strip(),
                        state_lic.strip(),
                        now,
                        "subscribed",
                    ),
                )
            conn.execute("COMMIT")
            return user_id
        except Exception:
            conn.execute("ROLLBACK")
            raise


# ─── Trial helpers ──────────────────────────────────────────────────────────


def trial_status(user_id: int) -> dict | None:
    """Return current trial state for a user. Returns dict with:
        is_trial (bool), expired (bool), lookups_remaining (int),
        days_remaining (int), expires_at (str)
    """
    from datetime import datetime, timezone
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT subscription_tier, trial_expires_at, trial_lookups_remaining
            FROM users WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
    if row is None:
        return None
    tier = row["subscription_tier"] or "trial"
    is_trial = tier == "trial"
    if not is_trial:
        return {
            "is_trial": False, "expired": False, "tier": tier,
            "lookups_remaining": None, "days_remaining": None,
            "expires_at": row["trial_expires_at"],
        }

    now = datetime.now(timezone.utc)
    expires_at_str = row["trial_expires_at"]
    days_remaining = 0
    expired_by_date = True
    if expires_at_str:
        try:
            expires_dt = datetime.fromisoformat(expires_at_str)
            if expires_dt.tzinfo is None:
                expires_dt = expires_dt.replace(tzinfo=timezone.utc)
            delta = expires_dt - now
            days_remaining = max(0, delta.days)
            expired_by_date = delta.total_seconds() <= 0
        except ValueError:
            pass

    lookups_remaining = int(row["trial_lookups_remaining"] or 0)
    expired_by_count = lookups_remaining <= 0
    expired = expired_by_date or expired_by_count
    return {
        "is_trial": True, "expired": expired, "tier": tier,
        "lookups_remaining": lookups_remaining,
        "days_remaining": days_remaining,
        "expires_at": expires_at_str,
        "expired_reason": (
            "lookups" if expired_by_count and not expired_by_date
            else "time" if expired_by_date and not expired_by_count
            else "both" if expired else None
        ),
    }


def decrement_trial_lookup(user_id: int) -> int:
    """Decrement trial_lookups_remaining by 1. Returns new value (may be 0)."""
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET trial_lookups_remaining = MAX(0, trial_lookups_remaining - 1) "
            "WHERE id = ? AND subscription_tier = 'trial'",
            (user_id,),
        )
        row = conn.execute(
            "SELECT trial_lookups_remaining FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return int(row["trial_lookups_remaining"] or 0) if row else 0


def update_subscription_tier(user_id: int, tier: str) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET subscription_tier = ? WHERE id = ?", (tier, user_id)
        )


# ─── Email + phone verification helpers ─────────────────────────────────────


def create_email_verification_token(user_id: int, ttl_hours: int = 48) -> str:
    from datetime import datetime, timedelta, timezone
    token = secrets.token_urlsafe(40)
    expires = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    with get_db() as conn:
        conn.execute(
            """INSERT INTO email_verification_tokens(token, user_id, created_at, expires_at)
               VALUES(?, ?, ?, ?)""",
            (token, user_id, utcnow_iso(), expires.isoformat(timespec="seconds")),
        )
    return token


def consume_email_verification_token(token: str) -> int | None:
    """Return user_id if token valid + unused + unexpired; mark verified."""
    if not token:
        return None
    with get_db() as conn:
        row = conn.execute(
            "SELECT user_id, expires_at, used_at FROM email_verification_tokens WHERE token = ?",
            (token,),
        ).fetchone()
        if row is None or row["used_at"] is not None:
            return None
        if row["expires_at"] <= utcnow_iso():
            return None
        user_id = int(row["user_id"])
        conn.execute(
            "UPDATE email_verification_tokens SET used_at = ? WHERE token = ?",
            (utcnow_iso(), token),
        )
        conn.execute(
            "UPDATE users SET email_verified_at = ? WHERE id = ?",
            (utcnow_iso(), user_id),
        )
        return user_id


def create_phone_verification_code(user_id: int) -> str:
    """Generate a 6-digit numeric code, store it, return it."""
    from datetime import datetime, timedelta, timezone
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    with get_db() as conn:
        conn.execute(
            """INSERT INTO phone_verification_codes(user_id, code, sent_at, expires_at)
               VALUES(?, ?, ?, ?)""",
            (user_id, code, utcnow_iso(), expires.isoformat(timespec="seconds")),
        )
    return code


def verify_phone_code(user_id: int, code: str) -> bool:
    """Check if code matches an active (unexpired, unused) code for this user."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT id, code, expires_at, used_at, attempts
               FROM phone_verification_codes
               WHERE user_id = ? AND used_at IS NULL
               ORDER BY sent_at DESC LIMIT 1""",
            (user_id,),
        ).fetchone()
        if row is None:
            return False
        # Always increment attempts to limit brute-force
        conn.execute(
            "UPDATE phone_verification_codes SET attempts = attempts + 1 WHERE id = ?",
            (row["id"],),
        )
        if int(row["attempts"] or 0) >= 5:
            return False
        if row["expires_at"] <= utcnow_iso():
            return False
        if str(row["code"]).strip() != str(code).strip():
            return False
        conn.execute(
            "UPDATE phone_verification_codes SET used_at = ? WHERE id = ?",
            (utcnow_iso(), row["id"]),
        )
        conn.execute(
            "UPDATE users SET phone_verified_at = ? WHERE id = ?",
            (utcnow_iso(), user_id),
        )
        return True


# ─── Stripe (card on file) helpers ──────────────────────────────────────────


def save_stripe_customer_id(user_id: int, customer_id: str) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET stripe_customer_id = ? WHERE id = ?",
            (customer_id, user_id),
        )


def save_stripe_payment_method(
    user_id: int, payment_method_id: str, brand: str | None, last4: str | None
) -> None:
    with get_db() as conn:
        conn.execute(
            """UPDATE users
               SET stripe_payment_method_id = ?, card_brand = ?, card_last4 = ?
               WHERE id = ?""",
            (payment_method_id, brand, last4, user_id),
        )


# ─── Marketing subscriber helpers ───────────────────────────────────────────


def subscribe_to_marketing(user_id: int) -> None:
    """Add user to marketing list with 'subscribed' tag. Idempotent."""
    user = get_user(user_id)
    if user is None:
        return
    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO marketing_subscribers(
                 user_id, email, full_name, phone, state_lic, subscribed_at, tags
               ) VALUES(?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id, user["email"], user["full_name"], user["phone"],
                user["state_lic"], utcnow_iso(), "subscribed",
            ),
        )
        conn.execute(
            "UPDATE users SET marketing_consent = 1, marketing_consent_at = ?, "
            "marketing_unsubscribed_at = NULL WHERE id = ?",
            (utcnow_iso(), user_id),
        )


def unsubscribe_from_marketing(user_id: int) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE marketing_subscribers SET unsubscribed_at = ? WHERE user_id = ?",
            (utcnow_iso(), user_id),
        )
        conn.execute(
            "UPDATE users SET marketing_consent = 0, marketing_unsubscribed_at = ? WHERE id = ?",
            (utcnow_iso(), user_id),
        )


# ─── Founder program helpers ────────────────────────────────────────────────


def founder_status() -> dict:
    """Returns counts for the public founder counter:
        slots_total, slots_taken, slots_remaining."""
    from lbt1 import config
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE founder_signup_number IS NOT NULL"
        ).fetchone()
    taken = int(row["n"] or 0) if row else 0
    return {
        "slots_total": config.FOUNDER_SLOTS,
        "slots_taken": taken,
        "slots_remaining": max(0, config.FOUNDER_SLOTS - taken),
        "discount_pct": config.FOUNDER_DISCOUNT_PCT,
        "pro_price_monthly": config.PRO_PRICE_MONTHLY,
        "founder_price_monthly": round(
            config.PRO_PRICE_MONTHLY * (100 - config.FOUNDER_DISCOUNT_PCT) / 100, 2
        ),
    }


# ─── Admin helpers ──────────────────────────────────────────────────────────


def is_admin_email(email: str) -> bool:
    from lbt1 import config
    return (email or "").strip().lower() in config.ADMIN_EMAILS


def list_users_for_admin(limit: int = 500) -> list[dict]:
    """All users with abuse + usage signals for the VA dashboard."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, email, full_name, phone, state_lic, locksmith_lic,
                   subscription_tier, founder_signup_number,
                   trial_lookups_remaining, total_lookups, total_lookup_seconds,
                   created_at, last_seen_at,
                   email_verified_at, phone_verified_at,
                   marketing_consent, signup_ip, signup_fingerprint,
                   banned_at, banned_reason
            FROM users
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        users = [dict(r) for r in rows]

        # Annotate abuse flags: same IP / fingerprint shared across users.
        ip_counts: dict[str, int] = {}
        fp_counts: dict[str, int] = {}
        for u in users:
            if u.get("signup_ip"):
                ip_counts[u["signup_ip"]] = ip_counts.get(u["signup_ip"], 0) + 1
            if u.get("signup_fingerprint"):
                fp_counts[u["signup_fingerprint"]] = fp_counts.get(u["signup_fingerprint"], 0) + 1
        for u in users:
            flags = []
            if u.get("signup_ip") and ip_counts.get(u["signup_ip"], 0) > 1:
                flags.append(f"shared-ip×{ip_counts[u['signup_ip']]}")
            if u.get("signup_fingerprint") and fp_counts.get(u["signup_fingerprint"], 0) > 1:
                flags.append(f"shared-fingerprint×{fp_counts[u['signup_fingerprint']]}")
            if not u.get("email_verified_at"):
                flags.append("email-unverified")
            if u.get("banned_at"):
                flags.append("banned")
            u["abuse_flags"] = flags
        return users


def ban_user(user_id: int, reason: str) -> None:
    with get_db() as conn:
        conn.execute(
            """UPDATE users SET subscription_tier = 'banned',
                                banned_at = ?, banned_reason = ?
               WHERE id = ?""",
            (utcnow_iso(), (reason or "")[:500], user_id),
        )
        # Invalidate any existing sessions for this user
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def unban_user(user_id: int) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET subscription_tier = 'trial', banned_at = NULL, banned_reason = NULL "
            "WHERE id = ?",
            (user_id,),
        )


def is_banned(user_id: int) -> bool:
    with get_db() as conn:
        row = conn.execute(
            "SELECT subscription_tier, banned_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        return False
    return (row["subscription_tier"] == "banned") or bool(row["banned_at"])


def marketing_subscribers_for_export() -> list[dict]:
    """Return all opted-in marketing subscribers — for CSV export."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT user_id, email, full_name, phone, state_lic, subscribed_at, tags
               FROM marketing_subscribers
               WHERE unsubscribed_at IS NULL
               ORDER BY subscribed_at DESC"""
        ).fetchall()
        return [dict(r) for r in rows]


def waitlist_for_export() -> list[dict]:
    """Users who exhausted their free lookups (= warm leads for the Brain platform)."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, email, full_name, phone, state_lic, locksmith_lic,
                      total_lookups, created_at, last_seen_at,
                      marketing_consent, founder_signup_number
               FROM users
               WHERE subscription_tier = 'trial'
                 AND trial_lookups_remaining = 0
               ORDER BY last_seen_at DESC"""
        ).fetchall()
        return [dict(r) for r in rows]


def get_user_by_email(email: str) -> sqlite3.Row | None:
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email.strip(),)
        ).fetchone()
        return row


def get_user(user_id: int) -> sqlite3.Row | None:
    with get_db() as db:
        return db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def touch_last_seen(user_id: int) -> None:
    with get_db() as db:
        db.execute("UPDATE users SET last_seen_at = ? WHERE id = ?", (utcnow_iso(), user_id))


# ─── Session helpers ─────────────────────────────────────────────────────────


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(48)
    expires = datetime.now(timezone.utc) + timedelta(days=config.SESSION_TTL_DAYS)
    with get_db() as db:
        db.execute(
            "INSERT INTO sessions(token, user_id, created_at, expires_at) VALUES(?, ?, ?, ?)",
            (token, user_id, utcnow_iso(), expires.isoformat(timespec="seconds")),
        )
    return token


def get_user_by_session(token: str) -> sqlite3.Row | None:
    if not token:
        return None
    with get_db() as db:
        row = db.execute(
            """
            SELECT u.* FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ? AND s.expires_at > ?
            """,
            (token, utcnow_iso()),
        ).fetchone()
        return row


def delete_session(token: str) -> None:
    with get_db() as db:
        db.execute("DELETE FROM sessions WHERE token = ?", (token,))


# ─── Password reset helpers ──────────────────────────────────────────────────


def create_reset_token(user_id: int, ttl_minutes: int = 30) -> str:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    with get_db() as db:
        db.execute(
            "INSERT INTO password_reset_tokens(token, user_id, created_at, expires_at) VALUES(?, ?, ?, ?)",
            (token, user_id, utcnow_iso(), expires.isoformat(timespec="seconds")),
        )
    return token


def consume_reset_token(token: str) -> int | None:
    """Return user_id if the token is valid and unused, else None. Marks it used."""
    with get_db() as db:
        row = db.execute(
            "SELECT user_id, expires_at, used_at FROM password_reset_tokens WHERE token = ?",
            (token,),
        ).fetchone()
        if row is None:
            return None
        if row["used_at"] is not None:
            return None
        if row["expires_at"] <= utcnow_iso():
            return None
        db.execute(
            "UPDATE password_reset_tokens SET used_at = ? WHERE token = ?",
            (utcnow_iso(), token),
        )
        return int(row["user_id"])


def update_password_hash(user_id: int, new_hash: str) -> None:
    with get_db() as db:
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id))


# ─── Lookup helpers ──────────────────────────────────────────────────────────


def record_lookup(
    *,
    user_id: int,
    vin: str,
    duration_seconds: int,
    result: dict[str, Any],
) -> int:
    """Persist a completed lookup and bump user counters in one transaction."""
    primary = (result.get("primary_result") or {}).get("oem_part_number")
    expires = (
        datetime.now(timezone.utc) + timedelta(days=config.VIN_RETENTION_DAYS)
    ).isoformat(timespec="seconds")

    with get_db() as db:
        db.execute("BEGIN")
        try:
            cur = db.execute(
                """
                INSERT INTO lookups(
                    user_id, vin, created_at, duration_seconds,
                    dealer_verification_status, primary_pn,
                    confidence_score, confidence_label,
                    result_json, expires_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    vin,
                    utcnow_iso(),
                    duration_seconds,
                    result.get("dealer_verification_status", "NOT_DEALER_VERIFIED_BY_VIN"),
                    primary,
                    float(result.get("confidence_score", 0.0)),
                    result.get("confidence_label", "LOW"),
                    json.dumps(result, default=str),
                    expires,
                ),
            )
            lookup_id = int(cur.lastrowid)  # type: ignore[arg-type]
            db.execute(
                """
                UPDATE users
                SET total_lookup_seconds = total_lookup_seconds + ?,
                    total_lookups = total_lookups + 1
                WHERE id = ?
                """,
                (duration_seconds, user_id),
            )
            db.execute("COMMIT")
            return lookup_id
        except Exception:
            db.execute("ROLLBACK")
            raise


def recent_lookups(user_id: int, limit: int = 20) -> list[sqlite3.Row]:
    with get_db() as db:
        rows = db.execute(
            """
            SELECT id, vin, created_at, duration_seconds,
                   dealer_verification_status, primary_pn,
                   confidence_score, confidence_label
            FROM lookups
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
        return list(rows)


def purge_expired_lookups() -> int:
    """Delete lookups whose retention has elapsed. Returns row count deleted."""
    with get_db() as db:
        cur = db.execute("DELETE FROM lookups WHERE expires_at <= ?", (utcnow_iso(),))
        return cur.rowcount or 0


# ─── Report helpers ──────────────────────────────────────────────────────────


def create_report(
    *,
    user_id: int,
    lookup_id: int | None,
    vin: str,
    part_number: str,
    issue: str,
    notes: str | None,
) -> int:
    with get_db() as db:
        cur = db.execute(
            """
            INSERT INTO part_reports(
                user_id, lookup_id, vin, part_number, issue, notes, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                lookup_id,
                vin.strip(),
                part_number.strip(),
                issue.strip(),
                (notes or "").strip() or None,
                utcnow_iso(),
            ),
        )
        return int(cur.lastrowid)  # type: ignore[arg-type]


def user_reports(user_id: int, limit: int = 50) -> list[sqlite3.Row]:
    with get_db() as db:
        rows = db.execute(
            """
            SELECT id, vin, part_number, issue, notes, created_at, resolved_at
            FROM part_reports
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
        return list(rows)


# ─── Util ────────────────────────────────────────────────────────────────────


def now_ts() -> int:
    return int(time.time())
