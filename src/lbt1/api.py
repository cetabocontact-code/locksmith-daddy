"""FastAPI app — auth (signup/signin/forgot/reset), protected VIN lookup,
search history, usage stats, and the click-to-report endpoint.

Run with:
    python -m lbt1.api
or:
    uvicorn lbt1.api:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from lbt1 import abuse, auth, config, db, notifications, pipeline, sms, stripe_client
from lbt1.models import LookupResult

log = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"

app = FastAPI(
    title="Locksmith Daddy — Tool 1",
    description="VIN-verified OEM key finder. Certified locksmiths only.",
    version="0.1.0",
)


@app.on_event("startup")
async def _startup() -> None:
    db.init_db()
    purged = db.purge_expired_lookups()
    if purged:
        log.info("Startup auto-purge removed %d expired lookup rows", purged)


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _render(template: str, **ctx: object) -> HTMLResponse:
    html = (TEMPLATE_DIR / template).read_text(encoding="utf-8")
    for k, v in ctx.items():
        html = html.replace("{{ " + k + " }}", str(v) if v is not None else "")
    # Strip any remaining unbound placeholders so they don't leak into the UI.
    import re
    html = re.sub(r"\{\{\s*[a-zA-Z_]+\s*\}\}", "", html)
    return HTMLResponse(html)


def _set_session_cookie(response: Response, token: str) -> None:
    secure = urlparse(config.BASE_URL).scheme == "https"
    response.set_cookie(
        key=config.SESSION_COOKIE_NAME,
        value=token,
        max_age=config.SESSION_TTL_DAYS * 86400,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(config.SESSION_COOKIE_NAME, path="/")


# ─── Public pages ────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    user = auth.current_user_or_none(request)
    if user is None:
        return RedirectResponse("/signin", status_code=status.HTTP_303_SEE_OTHER)
    return _render(
        "index.html",
        user_display=user["full_name"] or user["email"],
        user_email=user["email"],
        total_lookups=user["total_lookups"],
        total_seconds=user["total_lookup_seconds"],
    )


@app.get("/signin", response_class=HTMLResponse)
async def signin_page(request: Request, error: str = "") -> HTMLResponse:
    user = auth.current_user_or_none(request)
    if user is not None:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    return _render("signin.html", error=error)


@app.post("/signin")
async def signin_submit(
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
) -> Response:
    try:
        _, token = auth.signin(email=email, password=password)
    except auth.AuthError as exc:
        return RedirectResponse(
            f"/signin?error={_url_quote(str(exc))}", status_code=status.HTTP_303_SEE_OTHER
        )
    redir = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    _set_session_cookie(redir, token)
    return redir


@app.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request, error: str = "") -> HTMLResponse:
    user = auth.current_user_or_none(request)
    if user is not None:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    return _render("signup.html", error=error)


@app.post("/signup")
async def signup_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(...),
    phone: str = Form(...),
    state_lic: str = Form(...),
    locksmith_lic: str = Form(""),
    newsletter: str = Form(""),
    privacy_consent: str = Form(""),
    marketing: str = Form(""),
) -> Response:
    ip = abuse.client_ip(request)
    ua = request.headers.get("user-agent", "")
    fingerprint = abuse.browser_fingerprint(request)

    try:
        user_id, token = auth.signup(
            email=email,
            password=password,
            full_name=full_name,
            phone=phone,
            state_lic=state_lic,
            locksmith_lic=locksmith_lic or None,
            newsletter_opt_in=bool(newsletter),
            privacy_consent=bool(privacy_consent),
            marketing_consent=bool(marketing),
            signup_ip=ip,
            signup_user_agent=ua,
            signup_fingerprint=fingerprint,
        )
        abuse.log_signup_attempt(ip=ip, user_agent=ua, email=email, success=True)
    except (auth.AuthError, abuse.AbuseError) as exc:
        abuse.log_signup_attempt(ip=ip, user_agent=ua, email=email, success=False)
        return RedirectResponse(
            f"/signup?error={_url_quote(str(exc))}", status_code=status.HTTP_303_SEE_OTHER
        )

    # Email verification token (Layer 2). User must click the link before they
    # can do lookups — but they can still sign in.
    try:
        verify_token = db.create_email_verification_token(user_id)
        verify_url = f"{config.BASE_URL.rstrip('/')}/verify-email?token={verify_token}"
        notifications.send_signup_welcome_with_verify(
            to=email, full_name=full_name, verify_url=verify_url,
            trial_days=config.TRIAL_DAYS, trial_lookups=config.TRIAL_LOOKUPS,
        )
        if marketing:
            notifications.send_newsletter_confirmation(to=email, full_name=full_name)
    except Exception as exc:  # noqa: BLE001
        log.warning("Post-signup email best-effort failed: %s", exc)

    redir = RedirectResponse("/verify-email", status_code=status.HTTP_303_SEE_OTHER)
    _set_session_cookie(redir, token)
    return redir


# ─── Email verification (Layer 2) ────────────────────────────────────────────


@app.get("/verify-email", response_class=HTMLResponse)
async def verify_email_page(
    request: Request, token: str = "", error: str = "", message: str = ""
) -> Response:
    user = auth.current_user_or_none(request)
    # If token in query, attempt verification.
    if token:
        verified_user_id = db.consume_email_verification_token(token)
        if verified_user_id is not None:
            return RedirectResponse(
                "/verify-phone" if sms.is_enabled() else "/",
                status_code=status.HTTP_303_SEE_OTHER,
            )
        return _render("verify_email.html",
                       email=user["email"] if user else "",
                       error="That verification link is invalid or expired. Send a new one below.",
                       message="")
    # Show the "check your email" landing
    return _render("verify_email.html",
                   email=user["email"] if user else "",
                   error=error, message=message)


@app.post("/verify-email/resend")
async def verify_email_resend(user: dict = Depends(auth.require_user)) -> Response:
    if user.get("email_verified_at"):
        return RedirectResponse("/verify-email?message=Your+email+is+already+verified.",
                                status_code=status.HTTP_303_SEE_OTHER)
    token = db.create_email_verification_token(user["id"])
    verify_url = f"{config.BASE_URL.rstrip('/')}/verify-email?token={token}"
    notifications.send_email_verify_resend(
        to=user["email"], full_name=user["full_name"], verify_url=verify_url
    )
    return RedirectResponse(
        "/verify-email?message=Sent.+Check+your+email+(and+spam+folder).",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ─── Phone verification (Layer 2) ────────────────────────────────────────────


@app.get("/verify-phone", response_class=HTMLResponse)
async def verify_phone_page(request: Request, error: str = "", message: str = "") -> Response:
    user = auth.require_user(request)
    if user.get("phone_verified_at"):
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    return _render("verify_phone.html",
                   phone=user["phone"], error=error, message=message,
                   sms_enabled="true" if sms.is_enabled() else "false")


@app.post("/verify-phone/send")
async def verify_phone_send(user: dict = Depends(auth.require_user)) -> Response:
    code = db.create_phone_verification_code(user["id"])
    sent = sms.send_verification_code(user["phone"], code)
    msg = ("Code sent via SMS." if sent
           else "SMS isn't configured yet — your code is " + code + " (visible because SMS provider not set up).")
    return RedirectResponse(
        f"/verify-phone?message={_url_quote(msg)}", status_code=status.HTTP_303_SEE_OTHER
    )


@app.post("/verify-phone")
async def verify_phone_submit(
    user: dict = Depends(auth.require_user),
    code: str = Form(...),
) -> Response:
    if db.verify_phone_code(user["id"], code):
        # Optional: redirect to add-card step (Layer 3)
        next_step = "/add-card" if stripe_client.is_enabled() else "/"
        return RedirectResponse(next_step, status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(
        "/verify-phone?error=Code+is+wrong+or+expired.+Send+a+new+one.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ─── Card on file (Layer 3, optional) ────────────────────────────────────────


@app.get("/add-card", response_class=HTMLResponse)
async def add_card_page(request: Request) -> Response:
    user = auth.require_user(request)
    if not stripe_client.is_enabled():
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    # Get/create Stripe customer for this user
    customer_id = user.get("stripe_customer_id")
    if not customer_id:
        customer_id = stripe_client.create_customer(
            email=user["email"], name=user["full_name"], phone=user["phone"],
            metadata={"user_id": user["id"], "state_lic": user["state_lic"]},
        )
        if customer_id:
            db.save_stripe_customer_id(user["id"], customer_id)
    setup = stripe_client.create_setup_intent(customer_id) if customer_id else None
    if setup is None:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    return _render(
        "add_card.html",
        publishable_key=config.STRIPE_PUBLISHABLE_KEY,
        client_secret=setup["client_secret"],
    )


@app.post("/add-card/save")
async def add_card_save(
    user: dict = Depends(auth.require_user),
    payment_method_id: str = Form(...),
) -> Response:
    pm = stripe_client.get_payment_method(payment_method_id)
    if pm is None:
        return RedirectResponse("/add-card?error=Could+not+save+card.",
                                status_code=status.HTTP_303_SEE_OTHER)
    db.save_stripe_payment_method(
        user["id"], payment_method_id, pm.get("brand"), pm.get("last4")
    )
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


# ─── Subscribe to Pro (Stripe Checkout) ──────────────────────────────────────


@app.get("/subscribe", response_class=HTMLResponse)
async def subscribe_page(request: Request) -> Response:
    """Pro upgrade page. Shows founder pricing if available, regular if not."""
    user = auth.current_user_or_none(request)
    if user is None:
        return RedirectResponse("/signin", status_code=status.HTTP_303_SEE_OTHER)
    fs = db.founder_status()
    is_founder = bool(user.get("founder_signup_number")) and (
        user["founder_signup_number"] <= config.FOUNDER_SLOTS
    )
    price = fs["founder_price_monthly"] if is_founder else fs["pro_price_monthly"]
    return _render(
        "subscribe.html",
        site_brand=config.SITE_BRAND,
        is_founder="true" if is_founder else "false",
        founder_number=str(user.get("founder_signup_number") or ""),
        price=f"{price:.2f}",
        regular_price=f"{fs['pro_price_monthly']:.2f}",
        discount_pct=str(fs["discount_pct"]),
        slots_remaining=str(fs["slots_remaining"]),
        stripe_enabled="true" if stripe_client.is_enabled() else "false",
    )


@app.post("/subscribe/checkout")
async def subscribe_checkout(request: Request, user: dict = Depends(auth.require_user)) -> Response:
    if not stripe_client.is_enabled() or not config.STRIPE_PRICE_ID_PRO:
        return RedirectResponse("/subscribe?error=Stripe+not+configured+yet",
                                status_code=status.HTTP_303_SEE_OTHER)
    # Ensure customer exists
    customer_id = user.get("stripe_customer_id")
    if not customer_id:
        customer_id = stripe_client.create_customer(
            email=user["email"], name=user["full_name"], phone=user["phone"],
            metadata={"user_id": user["id"], "state_lic": user["state_lic"]},
        )
        if customer_id:
            db.save_stripe_customer_id(user["id"], customer_id)
    if not customer_id:
        return RedirectResponse("/subscribe?error=Could+not+create+customer",
                                status_code=status.HTTP_303_SEE_OTHER)

    # Founder discount?
    is_founder = bool(user.get("founder_signup_number")) and (
        user["founder_signup_number"] <= config.FOUNDER_SLOTS
    )
    discount = config.FOUNDER_DISCOUNT_PCT if is_founder else 0

    checkout_url = stripe_client.create_checkout_session(
        customer_id=customer_id,
        price_id=config.STRIPE_PRICE_ID_PRO,
        success_url=f"{config.BASE_URL.rstrip('/')}/subscribe/success",
        cancel_url=f"{config.BASE_URL.rstrip('/')}/subscribe",
        discount_pct=discount,
        user_id=user["id"],
    )
    if not checkout_url:
        return RedirectResponse("/subscribe?error=Could+not+start+checkout",
                                status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(checkout_url, status_code=status.HTTP_303_SEE_OTHER)


@app.get("/subscribe/success", response_class=HTMLResponse)
async def subscribe_success(request: Request) -> HTMLResponse:
    return HTMLResponse(
        f"<h2 style='font-family:sans-serif;color:#3fb950'>Welcome to Pro 🎉</h2>"
        f"<p>Your subscription is active. Your tier updates within 30 seconds via Stripe webhook.</p>"
        f"<p><a href='/'>Go to dashboard →</a></p>"
    )


@app.post("/webhook/stripe")
async def stripe_webhook(request: Request) -> dict:
    """Listen for checkout.session.completed and subscription.* events.

    Stripe POSTs here when a payment succeeds or a subscription changes status.
    """
    if not config.STRIPE_WEBHOOK_SECRET:
        # If not configured yet, accept all (insecure, but safe for testing).
        # In production this MUST be set.
        body = await request.body()
        import json as _json
        try:
            event = _json.loads(body)
        except Exception:
            return {"received": False}
    else:
        body = await request.body()
        sig = request.headers.get("stripe-signature", "")
        event = stripe_client.verify_webhook_signature(
            body, sig, config.STRIPE_WEBHOOK_SECRET
        )
        if event is None:
            return {"received": False, "error": "invalid signature"}

    event_type = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}

    if event_type == "checkout.session.completed":
        user_id_str = obj.get("client_reference_id")
        if user_id_str:
            try:
                user_id = int(user_id_str)
                db.update_subscription_tier(user_id, "pro")
                log.info("Promoted user %d to Pro via checkout.session.completed", user_id)
            except (ValueError, Exception) as exc:
                log.warning("Failed to promote user to Pro: %s", exc)

    elif event_type in ("customer.subscription.deleted", "customer.subscription.canceled"):
        # Subscription ended — drop user back to trial-expired state
        meta_user_id = (obj.get("metadata") or {}).get("user_id")
        if meta_user_id:
            try:
                db.update_subscription_tier(int(meta_user_id), "trial")
                log.info("Demoted user %s to trial on subscription end", meta_user_id)
            except Exception as exc:
                log.warning("Failed to demote user on sub end: %s", exc)

    return {"received": True}


# ─── Marketing unsubscribe ───────────────────────────────────────────────────


@app.get("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe_get(request: Request) -> Response:
    user = auth.require_user(request)
    db.unsubscribe_from_marketing(user["id"])
    return HTMLResponse(
        "<p>Unsubscribed from marketing emails. Transactional emails "
        "(password reset, billing) still go out.</p>"
    )


@app.post("/signout")
async def signout(
    response: Response,
    token: str | None = Cookie(default=None, alias=config.SESSION_COOKIE_NAME),
) -> Response:
    auth.signout(token)
    redir = RedirectResponse("/signin", status_code=status.HTTP_303_SEE_OTHER)
    _clear_session_cookie(redir)
    return redir


@app.get("/forgot", response_class=HTMLResponse)
async def forgot_page(message: str = "", error: str = "") -> HTMLResponse:
    return _render("forgot.html", message=message, error=error)


@app.post("/forgot")
async def forgot_submit(email: str = Form(...)) -> Response:
    """Always render the same success message — never confirm which emails
    are registered. If the email matches a user, queue a reset email."""
    row = db.get_user_by_email(email)
    if row is not None:
        token = db.create_reset_token(int(row["id"]))
        reset_url = f"{config.BASE_URL.rstrip('/')}/reset?token={token}"
        try:
            notifications.send_password_reset(to=email, reset_url=reset_url)
        except Exception as exc:  # noqa: BLE001
            log.warning("Reset email best-effort failed: %s", exc)
    msg = (
        "If an account exists for that email, a reset link has been sent. "
        "Check your inbox (and spam folder). The link is valid for 30 minutes."
    )
    return RedirectResponse(
        f"/forgot?message={_url_quote(msg)}", status_code=status.HTTP_303_SEE_OTHER
    )


@app.get("/reset", response_class=HTMLResponse)
async def reset_page(token: str = "", error: str = "") -> HTMLResponse:
    if not token:
        return _render("reset.html", token="", error="Reset link is missing or expired.")
    return _render("reset.html", token=token, error=error)


@app.post("/reset")
async def reset_submit(
    token: str = Form(...),
    password: str = Form(...),
) -> Response:
    if len(password) < 8:
        return RedirectResponse(
            f"/reset?token={token}&error={_url_quote('Password must be at least 8 characters.')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    user_id = db.consume_reset_token(token)
    if user_id is None:
        return RedirectResponse(
            f"/reset?error={_url_quote('Reset link is invalid or expired. Request a new one.')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    db.update_password_hash(user_id, auth.hash_password(password))
    return RedirectResponse(
        f"/signin?error={_url_quote('Password updated. Sign in with your new password.')}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ─── JSON API ────────────────────────────────────────────────────────────────


@app.get("/healthz")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# ─── Anti-AI / anti-scraper headers ──────────────────────────────────────────

@app.middleware("http")
async def _add_anti_ai_headers(request: Request, call_next):
    """Add X-Robots-Tag to discourage AI/LLM training scrapers.

    Honest scrapers (GPTBot, ClaudeBot, CCBot, Google-Extended, etc.) respect
    these tags. Combined with robots.txt and Cloudflare WAF, this keeps our
    tool's proprietary surface (dealer-resolution logic, query patterns) off
    public training datasets. Real user-facing pages still render normally —
    the header only affects automated crawlers.
    """
    response = await call_next(request)
    # noai/noimageai are the emerging conventions; noindex/nofollow are belt+suspenders.
    response.headers["X-Robots-Tag"] = "noai, noimageai, noindex, nofollow"
    return response


@app.get("/robots.txt", response_class=HTMLResponse)
async def robots_txt() -> HTMLResponse:
    """Block AI training crawlers and the actual lookup surface from honest bots."""
    body = (
        "User-agent: GPTBot\nDisallow: /\n\n"
        "User-agent: ClaudeBot\nDisallow: /\n\n"
        "User-agent: anthropic-ai\nDisallow: /\n\n"
        "User-agent: Google-Extended\nDisallow: /\n\n"
        "User-agent: CCBot\nDisallow: /\n\n"
        "User-agent: PerplexityBot\nDisallow: /\n\n"
        "User-agent: cohere-ai\nDisallow: /\n\n"
        "User-agent: Bytespider\nDisallow: /\n\n"
        "User-agent: meta-externalagent\nDisallow: /\n\n"
        "User-agent: *\n"
        "Disallow: /api/\n"
        "Disallow: /lookup\n"
        "Disallow: /admin\n"
        "Disallow: /buy/\n"
        "Disallow: /enterprise\n"
        "Allow: /\n"
    )
    return HTMLResponse(content=body, media_type="text/plain")


# ─── Static policy pages (privacy, refund, enterprise) ───────────────────────

@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page() -> HTMLResponse:
    return _render("privacy.html")


@app.get("/refund-policy", response_class=HTMLResponse)
async def refund_page() -> HTMLResponse:
    return _render("refund.html")


@app.get("/enterprise", response_class=HTMLResponse)
async def enterprise_page() -> HTMLResponse:
    return _render("enterprise.html", success_html="", error_html="")


@app.post("/enterprise")
async def enterprise_submit(
    request: Request,
    company: str = Form(...),
    contact_name: str = Form(...),
    contact_email: str = Form(...),
    phone: str = Form(""),
    role: str = Form(...),
    monthly_volume: str = Form(...),
    notes: str = Form(""),
) -> Response:
    """Capture enterprise / reseller lead → DB + best-effort email to Cetabo."""
    ip = abuse.client_ip(request)
    try:
        db.create_enterprise_lead(
            company=company,
            contact_name=contact_name,
            contact_email=contact_email,
            phone=phone or None,
            role=role,
            monthly_volume=monthly_volume,
            notes=notes or None,
            source_ip=ip,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Enterprise lead capture DB failed: %s", exc)
        return RedirectResponse(
            f"/enterprise?error={_url_quote('Could not save your request. Please email cetabo.contact@gmail.com.')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    # Best-effort email to ops inbox; don't block the user response on it.
    try:
        notifications.send_enterprise_lead_notification(
            company=company,
            contact_name=contact_name,
            contact_email=contact_email,
            phone=phone,
            role=role,
            monthly_volume=monthly_volume,
            notes=notes,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Enterprise lead email best-effort failed: %s", exc)
    return RedirectResponse("/enterprise?ok=1", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/api/founder-counter")
async def founder_counter() -> dict:
    """Public endpoint: how many founder spots remain. Used by landing/signup page."""
    return db.founder_status()


# ─── Admin (VA dashboard) ───────────────────────────────────────────────────


def _require_admin(request: Request) -> dict:
    user = auth.current_user_or_none(request)
    if user is None or not db.is_admin_email(user["email"]):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


@app.get("/api/admin/scrapfly-credits")
async def admin_scrapfly_credits(request: Request) -> dict:
    """Live ScrapFly credit balance for the admin dashboard."""
    _require_admin(request)
    from lbt1.scrapers.backends.scrapfly import ScrapFlyBackend
    if not config.SCRAPFLY_KEY:
        return {"configured": False}
    backend = ScrapFlyBackend(config.SCRAPFLY_KEY)
    try:
        status_data = await backend.get_credit_status()
    finally:
        await backend.close()
    if status_data is None:
        return {"configured": True, "error": "Could not fetch ScrapFly status"}
    # Add a warning flag for the dashboard
    remaining = status_data.get("remaining") or 0
    limit = status_data.get("limit") or 1
    pct = (remaining / limit * 100) if limit else 0
    status_data["configured"] = True
    status_data["percent_remaining"] = round(pct, 1)
    status_data["alert_level"] = (
        "critical" if remaining < 100
        else "warning" if remaining < 250
        else "ok"
    )
    return status_data


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request) -> Response:
    _require_admin(request)
    users = db.list_users_for_admin(limit=500)
    fs = db.founder_status()

    # Compact HTML — no separate template needed for this.
    import html as _html
    rows_html = []
    for u in users:
        flags = " ".join(
            f"<span class='flag'>{_html.escape(f)}</span>" for f in u.get("abuse_flags", [])
        )
        founder = f"#{u['founder_signup_number']}" if u.get("founder_signup_number") else "—"
        tier = u.get("subscription_tier", "trial")
        verified = "✓" if u.get("email_verified_at") else "—"
        last_seen = u.get("last_seen_at") or "—"
        actions = (
            f"<form method='post' action='/admin/unban/{u['id']}' style='display:inline'><button>Unban</button></form>"
            if tier == "banned"
            else f"""<form method='post' action='/admin/ban/{u['id']}' style='display:inline'>
                <input type='text' name='reason' placeholder='reason' required>
                <button>Ban</button></form>"""
        )
        rows_html.append(f"""
            <tr class='{"banned" if tier=="banned" else ""}'>
              <td>{u['id']}</td>
              <td>{_html.escape(u['email'])}<br><small>{_html.escape(u.get('full_name') or '')}</small></td>
              <td>{_html.escape(u.get('phone') or '')}<br><small>{_html.escape(u.get('state_lic') or '')}</small></td>
              <td>{tier}<br><small>{founder}</small></td>
              <td>{u.get('total_lookups', 0)} done<br><small>{u.get('trial_lookups_remaining', 0)} left</small></td>
              <td>{verified}<br><small>{_html.escape(str(u.get('signup_ip') or ''))}</small></td>
              <td>{flags}</td>
              <td>{_html.escape(str(last_seen)[:16])}</td>
              <td>{actions}</td>
            </tr>
        """)

    page = f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<title>Admin — {_html.escape(config.SITE_BRAND)}</title>
<style>
body {{ font-family: -apple-system, sans-serif; background: #0f1419; color: #e6edf3; padding: 24px; }}
h1 {{ font-size: 22px; }}
.toolbar {{ margin-bottom: 16px; display: flex; gap: 12px; align-items: center; }}
.toolbar a {{ background: #1a2027; color: #e6edf3; padding: 8px 14px; border-radius: 6px; text-decoration: none; border: 1px solid #2a3441; font-size: 13px; }}
.toolbar a:hover {{ border-color: #ff6b35; }}
.counter {{ color: #ff6b35; font-size: 14px; margin-left: auto; }}
table {{ width: 100%; border-collapse: collapse; font-size: 12px; background: #1a2027; border-radius: 6px; overflow: hidden; }}
th, td {{ padding: 8px 10px; border-bottom: 1px solid #2a3441; vertical-align: top; text-align: left; }}
th {{ background: #0f1419; color: #8b949e; font-weight: 600; text-transform: uppercase; font-size: 10px; }}
tr.banned {{ opacity: 0.5; }}
.flag {{ display: inline-block; background: rgba(248,81,73,0.15); color: #f85149; padding: 2px 6px; border-radius: 10px; font-size: 10px; margin-right: 4px; }}
small {{ color: #8b949e; }}
input[type=text] {{ background: #0f1419; color: #e6edf3; border: 1px solid #2a3441; padding: 4px 6px; border-radius: 4px; width: 110px; font-size: 12px; }}
button {{ background: #ff6b35; color: #fff; border: 0; padding: 5px 10px; border-radius: 4px; cursor: pointer; font-size: 11px; }}
</style></head>
<body>
<h1>Admin — {_html.escape(config.SITE_BRAND)}</h1>
<div class='toolbar'>
  <a href='/admin/export/marketing'>Export marketing subscribers CSV</a>
  <a href='/admin/export/waitlist'>Export waitlist CSV (free users at cap)</a>
  <a href='/'>← Back to app</a>
  <span class='counter'>Founders: {fs['slots_taken']} / {fs['slots_total']} taken ({fs['slots_remaining']} remaining)</span>
</div>
<div id='scrapfly-card' style='background:#1a2027; border:1px solid #2a3441; padding:14px; border-radius:6px; margin-bottom:16px; font-size:13px; display:flex; align-items:center; gap:14px;'>
  <strong>ScrapFly credits:</strong><span id='scrapfly-status'>Loading...</span>
  <span id='scrapfly-reset' style='color:#8b949e;'></span>
</div>
<script>
fetch('/api/admin/scrapfly-credits').then(r => r.json()).then(d => {{
  const el = document.getElementById('scrapfly-status');
  const reset = document.getElementById('scrapfly-reset');
  if (!d.configured) {{ el.textContent = 'Not configured'; return; }}
  if (d.error) {{ el.textContent = d.error; return; }}
  const color = d.alert_level === 'critical' ? '#f85149'
              : d.alert_level === 'warning' ? '#d29922'
              : '#3fb950';
  el.innerHTML = '<span style="color:' + color + '">' + d.remaining + ' / ' + d.limit + ' left (' + d.percent_remaining + '%)</span> · plan: ' + (d.plan || 'unknown');
  if (d.period_end) {{ reset.textContent = 'Resets: ' + d.period_end.slice(0,10); }}
}});
</script>
<table><thead>
  <tr><th>ID</th><th>Email / Name</th><th>Phone / Lic</th><th>Tier / Founder#</th>
  <th>Lookups</th><th>Verified / IP</th><th>Flags</th><th>Last seen</th><th>Action</th></tr>
</thead><tbody>{''.join(rows_html)}</tbody></table>
</body></html>"""
    return HTMLResponse(page)


@app.post("/admin/ban/{user_id}")
async def admin_ban(user_id: int, request: Request, reason: str = Form("")) -> Response:
    _require_admin(request)
    db.ban_user(user_id, reason)
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/unban/{user_id}")
async def admin_unban(user_id: int, request: Request) -> Response:
    _require_admin(request)
    db.unban_user(user_id)
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/admin/export/marketing")
async def admin_export_marketing(request: Request) -> Response:
    _require_admin(request)
    import csv as _csv
    from io import StringIO
    rows = db.marketing_subscribers_for_export()
    buf = StringIO()
    w = _csv.writer(buf)
    w.writerow(["user_id", "email", "full_name", "phone", "state_lic", "subscribed_at", "tags"])
    for r in rows:
        w.writerow([r["user_id"], r["email"], r["full_name"], r["phone"],
                    r["state_lic"], r["subscribed_at"], r["tags"]])
    return Response(
        content=buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="marketing_subscribers.csv"'},
    )


@app.get("/admin/export/waitlist")
async def admin_export_waitlist(request: Request) -> Response:
    _require_admin(request)
    import csv as _csv
    from io import StringIO
    rows = db.waitlist_for_export()
    buf = StringIO()
    w = _csv.writer(buf)
    w.writerow(["id", "email", "full_name", "phone", "state_lic", "locksmith_lic",
                "total_lookups", "created_at", "last_seen_at",
                "marketing_consent", "founder_signup_number"])
    for r in rows:
        w.writerow([r["id"], r["email"], r["full_name"], r["phone"], r["state_lic"],
                    r["locksmith_lic"], r["total_lookups"], r["created_at"],
                    r["last_seen_at"], r["marketing_consent"], r["founder_signup_number"]])
    return Response(
        content=buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="waitlist.csv"'},
    )


class LookupRequest(BaseModel):
    vin: str = Field(..., min_length=1, max_length=32)


@app.post("/api/lookup", response_model=LookupResult)
async def lookup(
    req: LookupRequest,
    user: dict = Depends(auth.require_user),
) -> LookupResult:
    """Run the pipeline + enforce trial limits + record the lookup.

    Enforcement order:
      1. Email must be verified (Layer-2 anti-abuse)
      2. Trial must still be active (date + lookups remaining)
      3. Decrement counter atomically before scraping
      4. Send "trial expired" email when this lookup uses the last credit
    """
    # 1. Email verification gate
    if not user.get("email_verified_at"):
        raise HTTPException(
            status_code=403,
            detail="Please verify your email first. Check your inbox for the verification link.",
        )

    # 2. Trial / subscription gate
    #
    # Policy (per user 2026-05-28): trial token is consumed ONLY when we
    # return DEALER_VERIFIED_BY_VIN. If the pipeline can't find verified
    # data, the lookup is free — we don't punish locksmiths for our
    # catalog gaps. Anti-abuse is handled separately via per-user/per-IP
    # rate limits + the verified-only gate (a spammer can't drain
    # ScrapFly credits faster than legit users can).
    trial = db.trial_status(user["id"])
    if trial and trial["is_trial"]:
        if trial["expired"]:
            reason = trial.get("expired_reason") or "time"
            msg = (
                "Your free trial has ended. Subscribe to keep looking up VINs."
                if reason == "time"
                else "You've used all your free trial lookups. Subscribe to keep going."
            )
            raise HTTPException(status_code=402, detail=msg)

    start = time.monotonic()
    log.info("Lookup VIN=%s user=%s tier=%s",
             req.vin, user["email"], user.get("subscription_tier", "trial"))
    result = await pipeline.lookup(req.vin)
    duration_s = int(round(time.monotonic() - start))

    # Only charge a trial token when we actually delivered VIN-verified data.
    remaining_after: int | None = None
    if (
        trial and trial["is_trial"]
        and result.dealer_verification_status == "DEALER_VERIFIED_BY_VIN"
    ):
        remaining_after = db.decrement_trial_lookup(user["id"])
        log.info("Trial token charged for VIN=%s user=%s remaining=%s",
                 req.vin, user["email"], remaining_after)
    elif trial and trial["is_trial"]:
        log.info("Trial token NOT charged (no verified PN) for VIN=%s user=%s",
                 req.vin, user["email"])

    try:
        db.record_lookup(
            user_id=user["id"],
            vin=req.vin,
            duration_seconds=duration_s,
            result=result.model_dump(mode="json"),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to record lookup: %s", exc)

    # If this lookup used the last trial credit, send the "trial ended" email.
    if remaining_after == 0:
        try:
            notifications.send_trial_expired(
                to=user["email"], full_name=user["full_name"], reason="lookups"
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("trial-expired email best-effort failed: %s", exc)

    log.info(
        "Lookup done VIN=%s user=%s status=%s primary=%s duration=%ds",
        req.vin, user["email"], result.dealer_verification_status,
        result.primary_result.oem_part_number if result.primary_result else None,
        duration_s,
    )

    # Methodology protection: hide research_steps + source_screenshots from
    # end users. These reveal which dealers we use, the disambiguation +
    # fallback logic, etc. — that's the competitive moat. Admins still see
    # the full trace via the /api/admin/lookup endpoint. The dealer
    # source_url on each part stays (locksmiths use it to verify the PN).
    if not db.is_admin_email(user.get("email") or ""):
        result = result.model_copy(update={
            "research_steps": [],
            "source_screenshots": [],
        })

    return result


@app.get("/api/me/trial-status")
async def trial_status_api(user: dict = Depends(auth.require_user)) -> dict:
    """Returns trial state so the frontend can show banners / paywalls."""
    return db.trial_status(user["id"]) or {"is_trial": False}


class ReportRequest(BaseModel):
    vin: str = Field(..., min_length=1, max_length=32)
    part_number: str = Field(..., min_length=1, max_length=64)
    issue: str = Field(..., min_length=1, max_length=64)
    notes: str = Field("", max_length=2000)
    lookup_id: int | None = None


@app.post("/api/report")
async def report_part(
    req: ReportRequest,
    user: dict = Depends(auth.require_user),
) -> dict[str, object]:
    report_id = db.create_report(
        user_id=user["id"],
        lookup_id=req.lookup_id,
        vin=req.vin,
        part_number=req.part_number,
        issue=req.issue,
        notes=req.notes,
    )
    log.info(
        "Report filed id=%d user=%s vin=%s pn=%s issue=%r",
        report_id, user["email"], req.vin, req.part_number, req.issue,
    )
    return {"ok": True, "report_id": report_id}


@app.get("/api/me")
async def me(user: dict = Depends(auth.require_user)) -> dict:
    return user


@app.get("/api/me/lookups")
async def my_lookups(user: dict = Depends(auth.require_user)) -> list[dict]:
    rows = db.recent_lookups(user["id"], limit=20)
    return [dict(r) for r in rows]


@app.get("/api/me/reports")
async def my_reports(user: dict = Depends(auth.require_user)) -> list[dict]:
    rows = db.user_reports(user["id"], limit=50)
    return [dict(r) for r in rows]


# ─── Utility ─────────────────────────────────────────────────────────────────


def _url_quote(s: str) -> str:
    from urllib.parse import quote
    return quote(s, safe="")


def main() -> None:
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    uvicorn.run("lbt1.api:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
