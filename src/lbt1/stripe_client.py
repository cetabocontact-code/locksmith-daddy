"""Stripe wrapper (Layer 3 anti-abuse + paid subscriptions).

Two use cases:
  1. **Setup Intent** at signup (Layer 3): collect a card on file without
     charging, blocks ~95% of casual trial abuse. Card later auto-charged
     when trial converts.
  2. **Subscriptions**: charge $19.99/mo Pro or $49.99/mo Shop.

If STRIPE_SECRET_KEY is unset, every call is a no-op that returns None and
logs a warning. Signup proceeds without the card-on-file step.

Env vars:
    STRIPE_SECRET_KEY (sk_test_… or sk_live_…)
    STRIPE_PUBLISHABLE_KEY (pk_test_… or pk_live_…) — used by the frontend
    STRIPE_PRICE_ID_PRO (price_…)  — recurring $19.99/mo
    STRIPE_PRICE_ID_SHOP (price_…) — recurring $49.99/mo per seat
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from lbt1 import config

log = logging.getLogger(__name__)

API_BASE = "https://api.stripe.com/v1"


def is_enabled() -> bool:
    return bool(config.STRIPE_SECRET_KEY)


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=API_BASE,
        auth=(config.STRIPE_SECRET_KEY, ""),
        timeout=20.0,
    )


def create_customer(*, email: str, name: str, phone: str, metadata: dict | None = None) -> str | None:
    """Create a Stripe Customer. Returns customer ID or None if Stripe disabled."""
    if not is_enabled():
        log.info("Stripe not configured — skipping create_customer for %s", email)
        return None
    data: dict[str, Any] = {"email": email, "name": name, "phone": phone}
    if metadata:
        for k, v in metadata.items():
            data[f"metadata[{k}]"] = str(v)
    try:
        with _client() as c:
            resp = c.post("/customers", data=data)
            resp.raise_for_status()
            return resp.json()["id"]
    except Exception as exc:  # noqa: BLE001
        log.warning("Stripe create_customer failed: %s", exc)
        return None


def create_setup_intent(customer_id: str) -> dict | None:
    """Create a SetupIntent for saving a card on file (no charge).
    Returns dict with client_secret and id, for the frontend Stripe.js flow."""
    if not is_enabled() or not customer_id:
        return None
    try:
        with _client() as c:
            resp = c.post(
                "/setup_intents",
                data={
                    "customer": customer_id,
                    "payment_method_types[]": "card",
                    "usage": "off_session",
                },
            )
            resp.raise_for_status()
            j = resp.json()
            return {"id": j["id"], "client_secret": j["client_secret"]}
    except Exception as exc:  # noqa: BLE001
        log.warning("Stripe create_setup_intent failed: %s", exc)
        return None


def get_payment_method(payment_method_id: str) -> dict | None:
    """Return {brand, last4} or None. Used after Setup Intent succeeds to
    record what card we have on file (don't store full card data — Stripe holds it)."""
    if not is_enabled() or not payment_method_id:
        return None
    try:
        with _client() as c:
            resp = c.get(f"/payment_methods/{payment_method_id}")
            resp.raise_for_status()
            j = resp.json()
            card = j.get("card") or {}
            return {"brand": card.get("brand"), "last4": card.get("last4")}
    except Exception as exc:  # noqa: BLE001
        log.warning("Stripe get_payment_method failed: %s", exc)
        return None


def create_subscription(customer_id: str, price_id: str) -> str | None:
    """Start a recurring subscription. Returns subscription ID."""
    if not is_enabled() or not customer_id or not price_id:
        return None
    try:
        with _client() as c:
            resp = c.post(
                "/subscriptions",
                data={"customer": customer_id, "items[0][price]": price_id},
            )
            resp.raise_for_status()
            return resp.json()["id"]
    except Exception as exc:  # noqa: BLE001
        log.warning("Stripe create_subscription failed: %s", exc)
        return None


def create_checkout_session(
    *,
    customer_id: str,
    price_id: str,
    success_url: str,
    cancel_url: str,
    discount_pct: int = 0,
    user_id: int | None = None,
) -> str | None:
    """Create a Stripe Checkout session. Returns the hosted-checkout URL.

    For founders (discount_pct > 0), we apply a one-time coupon discount that
    persists for the lifetime of the subscription.
    """
    if not is_enabled() or not customer_id or not price_id:
        return None
    data: dict[str, Any] = {
        "mode": "subscription",
        "customer": customer_id,
        "line_items[0][price]": price_id,
        "line_items[0][quantity]": "1",
        "success_url": success_url,
        "cancel_url": cancel_url,
        # Stripe auto-enables Apple Pay + Google Pay when payment_method_types
        # is left to defaults. Explicitly enabling just card is also OK.
        "automatic_tax[enabled]": "true",
        "allow_promotion_codes": "true",
    }
    if user_id:
        data["client_reference_id"] = str(user_id)
        data["subscription_data[metadata][user_id]"] = str(user_id)

    # Apply a percent-off coupon for founders. We create a one-time coupon
    # (or reuse one if Stripe rejects duplicates) and attach it to the session.
    if discount_pct > 0:
        coupon_id = _ensure_founder_coupon(discount_pct)
        if coupon_id:
            data["discounts[0][coupon]"] = coupon_id

    try:
        with _client() as c:
            resp = c.post("/checkout/sessions", data=data)
            resp.raise_for_status()
            return resp.json()["url"]
    except Exception as exc:  # noqa: BLE001
        log.warning("Stripe create_checkout_session failed: %s", exc)
        return None


def _ensure_founder_coupon(discount_pct: int) -> str | None:
    """Get-or-create a forever-recurring coupon for founder pricing.

    Stripe's coupons can be percent_off + duration=forever to permanently
    discount any subscription it's attached to.
    """
    coupon_id = f"founder-{discount_pct}pct"
    try:
        with _client() as c:
            # Try to fetch existing.
            resp = c.get(f"/coupons/{coupon_id}")
            if resp.status_code == 200:
                return coupon_id
            # Create new.
            resp = c.post(
                "/coupons",
                data={
                    "id": coupon_id,
                    "percent_off": str(discount_pct),
                    "duration": "forever",
                    "name": f"Founder ({discount_pct}% off forever)",
                },
            )
            if resp.status_code in (200, 201):
                return coupon_id
            log.warning("Coupon ensure failed (%d): %s", resp.status_code, resp.text[:200])
            return None
    except Exception as exc:  # noqa: BLE001
        log.warning("Stripe _ensure_founder_coupon failed: %s", exc)
        return None


def verify_webhook_signature(payload: bytes, sig_header: str, secret: str) -> dict | None:
    """Manually verify Stripe webhook signature using HMAC-SHA256.

    We avoid the official `stripe` SDK to keep deps light. Returns the
    parsed event dict on success, None on failure.
    """
    import hashlib
    import hmac
    import json as _json
    import time as _time
    if not secret or not sig_header:
        return None
    try:
        # sig_header format: t=1492774577,v1=signature,v0=signature
        parts = dict(p.split("=", 1) for p in sig_header.split(",") if "=" in p)
        timestamp = parts.get("t", "")
        signature = parts.get("v1", "")
        if not timestamp or not signature:
            return None
        # Reject events older than 5 minutes (replay attack protection)
        if abs(int(_time.time()) - int(timestamp)) > 300:
            return None
        signed_payload = f"{timestamp}.{payload.decode('utf-8')}"
        expected = hmac.new(
            secret.encode("utf-8"), signed_payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return None
        return _json.loads(payload.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.warning("Webhook signature verification failed: %s", exc)
        return None
