"""Environment-driven configuration. All values have safe defaults so the app
runs locally with zero setup; production overrides come from env vars."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

# Load .env at import time so env vars work without an explicit shell command.
# dotenv is optional — if it isn't installed, we just rely on os.environ.
try:
    from dotenv import load_dotenv  # type: ignore

    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    load_dotenv(_PROJECT_ROOT / ".env", override=False)
except ImportError:
    pass


def _env(key: str, default: str = "") -> str:
    v = os.environ.get(key)
    return v if v is not None else default


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _ensure_secret_in_data_dir(data_dir: Path) -> str:
    """If LBT1_SECRET_KEY is unset, write a stable random one to data/.secret_key
    so cookies survive process restarts. Production should set the env var."""
    path = data_dir / ".secret_key"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    value = secrets.token_urlsafe(48)
    path.write_text(value, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return value


# Directories
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(_env("LBT1_DATA_DIR", str(PROJECT_ROOT / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Database
DB_PATH = Path(_env("LBT1_DB_PATH", str(DATA_DIR / "lbt1.db")))

# Sessions
SESSION_COOKIE_NAME = "lbt1_session"
SESSION_TTL_DAYS = _env_int("LBT1_SESSION_TTL_DAYS", 30)
SECRET_KEY = _env("LBT1_SECRET_KEY", "") or _ensure_secret_in_data_dir(DATA_DIR)

# VIN retention
VIN_RETENTION_DAYS = _env_int("LBT1_VIN_RETENTION_DAYS", 60)

# Public-facing URL — used in emails (e.g. password-reset links). Override on deploy.
BASE_URL = _env("LBT1_BASE_URL", "http://127.0.0.1:8000")
SITE_DOMAIN = _env("LBT1_SITE_DOMAIN", "locksmithdaddy.us")
LEGAL_ENTITY = _env("LBT1_LEGAL_ENTITY", "Cetabo LLC")

# SMTP — all optional; emails are best-effort.
SMTP_HOST = _env("SMTP_HOST")
SMTP_PORT = _env_int("SMTP_PORT", 587)
SMTP_USER = _env("SMTP_USER")
SMTP_PASS = _env("SMTP_PASS")
SMTP_USE_TLS = _env_bool("SMTP_USE_TLS", True)
EMAIL_FROM = _env("EMAIL_FROM", "Locksmith Daddy <noreply@locksmithdaddy.us>")
EMAIL_ENABLED = bool(SMTP_HOST and SMTP_USER and SMTP_PASS)

# Scraping backend selection
# Values: auto (default) | scrapingant | brightdata | local
SCRAPE_BACKEND = _env("LBT1_SCRAPE_BACKEND", "auto")
SCRAPINGANT_API_KEY = _env("SCRAPINGANT_API_KEY")
BRIGHTDATA_API_KEY = _env("BRIGHTDATA_API_KEY")
BRIGHTDATA_ZONE = _env("BRIGHTDATA_ZONE")
SCRAPERAPI_KEY = _env("SCRAPERAPI_KEY")
SCRAPFLY_KEY = _env("SCRAPFLY_KEY")
APIFY_TOKEN = _env("APIFY_TOKEN")

# Brand (single env var so we can rename without code changes)
SITE_BRAND = _env("LBT1_SITE_BRAND", "Locksmith Daddy")
SITE_TAGLINE = _env("LBT1_SITE_TAGLINE", "VIN Key Finder")

# Trial mechanics
# - TRIAL_LOOKUPS = how many free lookups every new user gets (one-time pool)
# - TRIAL_DAYS = max trial age in days; set extremely high to effectively disable
#   the date-based expiry. Trial ends when lookups hit 0 OR date passes.
TRIAL_DAYS = _env_int("LBT1_TRIAL_DAYS", 36500)  # 100 years = effectively no expiry
TRIAL_LOOKUPS = _env_int("LBT1_TRIAL_LOOKUPS", 10)

# Founder program — first N signups get a permanent discount on Pro.
FOUNDER_SLOTS = _env_int("LBT1_FOUNDER_SLOTS", 100)
FOUNDER_DISCOUNT_PCT = _env_int("LBT1_FOUNDER_DISCOUNT_PCT", 50)
PRO_PRICE_MONTHLY = float(_env("LBT1_PRO_PRICE_MONTHLY", "79"))

# Admin (comma-separated emails that can access /admin)
ADMIN_EMAILS = [
    e.strip().lower() for e in _env("LBT1_ADMIN_EMAILS", "").split(",") if e.strip()
]

# SMS (Twilio) — optional, for Layer-2 phone verification
TWILIO_ACCOUNT_SID = _env("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = _env("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = _env("TWILIO_FROM_NUMBER")

# Stripe — optional, for Layer-3 card-on-file + subscriptions
STRIPE_SECRET_KEY = _env("STRIPE_SECRET_KEY")
STRIPE_PUBLISHABLE_KEY = _env("STRIPE_PUBLISHABLE_KEY")
STRIPE_PRICE_ID_PRO = _env("STRIPE_PRICE_ID_PRO")
STRIPE_PRICE_ID_SHOP = _env("STRIPE_PRICE_ID_SHOP")
STRIPE_WEBHOOK_SECRET = _env("STRIPE_WEBHOOK_SECRET")
