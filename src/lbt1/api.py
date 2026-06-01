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
    # NOTE: manual_pn_overrides table exists in schema for audit/reference
    # of human-confirmed VIN→PN cases (phone calls, manual dealer-site
    # checks), but the pipeline does NOT consult it. The product promise
    # is "verified live against the dealer's current catalog for THIS exact
    # VIN" — returning memorized answers breaks that promise. YMM lookups
    # are commodity; VIN-verified PN is our moat.


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
    """Public homepage. Shows the VIN entry form — no signin required.
    Authed users with credits still see this form (they can use credits at
    /lookup if they're signed in, or use the public paywall flow if they
    want to do one-offs without burning credits)."""
    return _render("home_public.html")


@app.get("/me", response_class=HTMLResponse)
async def member_dashboard(request: Request) -> HTMLResponse:
    """Signed-in member dashboard — lookup history, credit balance,
    account settings. The old `index.html` content."""
    user = auth.current_user_or_none(request)
    if user is None:
        return RedirectResponse("/signin?next=/me", status_code=status.HTTP_303_SEE_OTHER)
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
        # Handle anonymous one-time pack purchases (job_id metadata present)
        meta = obj.get("metadata") or {}
        job_id = meta.get("job_id")
        kind = meta.get("kind")
        credits_str = meta.get("credits")
        session_id = obj.get("id") or ""
        if job_id:
            # Unlock the specific paywalled job result
            try:
                newly_paid = db.mark_job_paid(job_id, session_id)
                log.info(
                    "Stripe webhook: job %s marked paid (newly=%s, kind=%s)",
                    job_id, newly_paid, kind,
                )
                # If 10-pack was purchased on top of a single-VIN unlock, the
                # extra 9 credits accrue once they create an account. We
                # record the pending purchase; grant on account creation.
                if kind == "ten" and credits_str:
                    try:
                        amt = int(obj.get("amount_total") or 4900)
                        db.record_pending_purchase(
                            stripe_session_id=session_id, pack_kind=kind,
                            credits=int(credits_str), amount_cents=amt,
                            customer_email=(obj.get("customer_details") or {}).get("email"),
                        )
                    except Exception as e:  # noqa: BLE001
                        log.warning("10-pack pending-purchase record failed: %s", e)
            except Exception as exc:  # noqa: BLE001
                log.warning("Failed to mark job %s paid: %s", job_id, exc)
        elif kind in ("single", "ten"):
            # 10-pack purchased standalone (no job_id, from the upsell after
            # an unlocked single, or from a future /pricing page).
            try:
                amt = int(obj.get("amount_total") or (4900 if kind == "ten" else 799))
                db.record_pending_purchase(
                    stripe_session_id=session_id, pack_kind=kind,
                    credits=int(credits_str or (10 if kind == "ten" else 1)),
                    amount_cents=amt,
                    customer_email=(obj.get("customer_details") or {}).get("email"),
                )
                log.info("Standalone pack purchase recorded: kind=%s session=%s", kind, session_id)
            except Exception as exc:  # noqa: BLE001
                log.warning("Standalone pack record failed: %s", exc)

        # Legacy subscription path (Pro $79/mo) — keep working for any
        # existing customers from before the per-VIN model.
        user_id_str = obj.get("client_reference_id")
        if user_id_str and not job_id:
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


@app.post("/contact")
async def contact_submit(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    message: str = Form(...),
) -> JSONResponse:
    """Contact-modal form endpoint. Saves to contact_messages + best-effort
    emails cetabo.contact@gmail.com. Returns JSON for the modal to show
    'Thanks, we'll get back to you' without a page reload."""
    name = (name or "").strip()
    email = (email or "").strip().lower()
    message = (message or "").strip()
    if not name or not email or not message:
        return JSONResponse(
            {"error": "Please fill in name, email, and message."},
            status_code=400,
        )
    if "@" not in email:
        return JSONResponse({"error": "Email looks invalid."}, status_code=400)
    if len(message) > 5000:
        return JSONResponse({"error": "Message too long (max 5000 chars)."}, status_code=400)
    ip = abuse.client_ip(request)
    try:
        db.create_contact_message(
            name=name, email=email, message=message, source_ip=ip,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Contact DB save failed: %s", exc)
        return JSONResponse(
            {"error": "Could not save your message. Email cetabo.contact@gmail.com directly."},
            status_code=500,
        )
    try:
        notifications.send(
            "cetabo.contact@gmail.com",
            f"[LD Contact] {name} via homepage form",
            (
                f"New contact-form message from the Locksmith Daddy homepage:\n\n"
                f"Name:    {name}\n"
                f"Email:   {email}\n\n"
                f"Message:\n{message}\n\n"
                f"— Locksmith Daddy automated form (source IP {ip})\n"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Contact ops-inbox email best-effort failed: %s", exc)
    return JSONResponse({"ok": True})


# ─── Public paywalled VIN lookup (no signin required) ────────────────────────
#
# Flow (matches the user-spec click-path):
#   1. GET  /                       -> home_public.html (VIN form)
#   2. POST /lookup                 -> create job + start pipeline in background
#                                      returns {job_id}
#   3. GET  /lookup/{job_id}/status -> poll for vehicle decode + verification
#                                      NEVER returns the PN; only status flags
#   4. GET  /buy/single?job_id=X    -> Stripe Checkout session ($7.99 one-time)
#                                      with metadata.job_id
#   5. POST /webhook/stripe         -> mark job paid_at + grant 1 credit (10
#                                      for the 10-pack) via existing handler
#   6. GET  /result/{job_id}        -> RENDERS THE PN, only if paid_at is set
#
# Security invariants:
#   - The PN lives ONLY in the lookup_jobs.primary_pn column server-side.
#   - GET /lookup/{job_id}/status returns a payload that omits primary_pn,
#     alt_pns, and dealer_url — they are NEVER on the wire pre-payment.
#   - GET /result/{job_id} uses get_lookup_job_paid_result, which is the only
#     codepath that selects primary_pn, and only when paid_at IS NOT NULL.


_VIN_RE = __import__("re").compile(r"^[A-HJ-NPR-Z0-9]{17}$")


@app.post("/lookup")
async def public_lookup_submit(
    request: Request,
    vin: str = Form(...),
    email: str = Form(""),
) -> JSONResponse:
    """Anonymous VIN lookup entry point. Creates a queued job, fires the
    pipeline in background, returns the job_id immediately.

    The pipeline writes its result to the DB; the browser polls
    /lookup/{job_id}/status to get updates and reveal-eligibility.
    """
    vin_clean = (vin or "").strip().upper()
    if not _VIN_RE.match(vin_clean):
        return JSONResponse(
            {"error": "VIN must be 17 alphanumeric characters (no I, O, or Q)."},
            status_code=400,
        )
    email_clean = (email or "").strip().lower() or None
    if email_clean and "@" not in email_clean:
        return JSONResponse({"error": "Email looks invalid."}, status_code=400)

    ip = abuse.client_ip(request)

    # Lightweight abuse gate: cap anonymous lookups per IP per hour.
    # 10/hour is enough for any human; scrapers will hit this fast.
    try:
        recent = abuse.count_anonymous_lookups_last_hour(ip)
        if recent >= 10:
            return JSONResponse(
                {"error": "Too many requests from your network. Try again in an hour, or sign in."},
                status_code=429,
            )
    except Exception:  # noqa: BLE001 — best-effort
        pass

    job_id = db.create_lookup_job(vin=vin_clean, email=email_clean, source_ip=ip)

    # Run the pipeline in the background — the HTTP request returns immediately.
    import asyncio
    asyncio.create_task(_run_anonymous_lookup_job(job_id, vin_clean, email_clean))

    return JSONResponse({"job_id": job_id, "status": "queued"})


async def _run_anonymous_lookup_job(job_id: str, vin: str, email: str | None) -> None:
    """Background worker: decode VIN, run dealer pipeline, store result.
    Never raises (always finalizes the job row, even on error)."""
    from time import perf_counter
    started = perf_counter()
    profile = None
    try:
        # Step 1: decode via NHTSA (cheap, fast) and stamp the vehicle on the
        # job so the browser sees "Decoded: 2025 Hyundai Elantra" while the
        # dealer scrape is still running.
        try:
            from lbt1.vin import decoder
            profile = await decoder.decode(vin)
            db.update_lookup_job_decoded(
                job_id,
                year=profile.year,
                make=profile.make,
                model=profile.model,
                trim=profile.trim,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("NHTSA decode failed for %s: %s", vin, exc)
            db.finish_lookup_job(
                job_id, primary_pn=None, alt_pns=None, dealer_url=None,
                confidence_label="LOW",
                duration_seconds=int(perf_counter() - started),
                error_message="Could not decode VIN with NHTSA.",
            )
            _send_result_email(email, job_id, profile, verified=False, error=True)
            return

        # Step 2: full dealer-verification pipeline. Always runs live —
        # we never return memorized PNs even when a sibling VIN has been
        # verified before. The product promise is "the dealer's catalog
        # confirmed THIS exact VIN's PN right now, on this lookup."
        result = await pipeline.lookup(vin)
        pn = None
        alts: list[str] = []
        dealer_url = None
        if result.primary_result:
            pn = result.primary_result.oem_part_number
            dealer_url = result.primary_result.source_url
            alts = [
                p.oem_part_number for p in (result.alternative_matches or [])
                if p.oem_part_number and p.oem_part_number != pn
            ]
        verified = result.dealer_verification_status == "DEALER_VERIFIED_BY_VIN"
        db.finish_lookup_job(
            job_id,
            primary_pn=pn if verified else None,
            alt_pns=alts if verified else None,
            dealer_url=dealer_url if verified else None,
            confidence_label=result.confidence_label,
            duration_seconds=int(perf_counter() - started),
        )
        _send_result_email(email, job_id, profile, verified=verified)
    except Exception as exc:  # noqa: BLE001
        log.exception("Background lookup job %s crashed", job_id)
        try:
            db.finish_lookup_job(
                job_id, primary_pn=None, alt_pns=None, dealer_url=None,
                confidence_label="LOW",
                duration_seconds=int(perf_counter() - started),
                error_message="A transient error occurred. You were not charged.",
            )
            _send_result_email(email, job_id, profile, verified=False, error=True)
        except Exception:  # noqa: BLE001
            pass


def _send_result_email(
    email: str | None, job_id: str, profile, *,
    verified: bool, error: bool = False,
) -> None:
    """Send the result-ready email. Sends for BOTH verified and unverified
    outcomes so the user knows the lookup finished even if no PN was found.
    The PN is NEVER in the email — only a link to the paywalled unlock page.
    Best-effort: SMTP outages or unconfigured email do not affect anything."""
    if not email:
        return
    try:
        base = config.BASE_URL.rstrip("/")
        vehicle_label = ""
        if profile is not None:
            parts = [
                str(profile.year) if getattr(profile, "year", None) else "",
                getattr(profile, "make", "") or "",
                getattr(profile, "model", "") or "",
            ]
            vehicle_label = " ".join(p for p in parts if p).strip()

        if error:
            subject = "Locksmith Daddy — lookup hit a snag"
            body = (
                f"Hi there,\n\n"
                f"Your Locksmith Daddy lookup for "
                f"{vehicle_label or 'your VIN'} ran into a transient error "
                f"on our side. You were not charged.\n\n"
                f"Please try again here: {base}/\n\n"
                f"If it happens twice in a row, reply to this email and "
                f"we'll resolve it manually.\n\n"
                f"— Locksmith Daddy\n"
                f"   a Cetabo LLC venture\n"
            )
        elif verified:
            ready_url = f"{base}/lookup/{job_id}"
            subject = "Your Locksmith Daddy result is ready"
            body = (
                f"Good news — we found a dealer-verified OEM part number "
                f"for your {vehicle_label or 'VIN'}.\n\n"
                f"Click to unlock for $7.99:\n  {ready_url}\n\n"
                f"You only pay when you click and complete checkout. The "
                f"unlocked page will show the part number plus a link to "
                f"the dealer's own product page as proof of fitment.\n\n"
                f"— Locksmith Daddy\n"
                f"   a Cetabo LLC venture\n"
            )
        else:
            subject = "Locksmith Daddy — VIN not yet verified"
            body = (
                f"Your lookup for {vehicle_label or 'your VIN'} finished.\n\n"
                f"The dealer catalog hasn't published a verified OEM key "
                f"fitment for this exact year + trim yet. You were not "
                f"charged.\n\n"
                f"This usually means a brand-new 2026 trim where the "
                f"dealer's catalog data lags the vehicle release. Try "
                f"again in a few weeks, or for high-priority research "
                f"requests use the Enterprise option at:\n"
                f"  {base}/enterprise\n\n"
                f"— Locksmith Daddy\n"
                f"   a Cetabo LLC venture\n"
            )
        notifications.send(email, subject, body)
    except Exception as exc:  # noqa: BLE001
        log.warning("Result email best-effort failed: %s", exc)


@app.get("/lookup/{job_id}/status")
async def public_lookup_status(job_id: str) -> JSONResponse:
    """Browser polls this every few seconds. Never returns the PN."""
    job = db.get_lookup_job_public(job_id)
    if not job:
        return JSONResponse({"error": "Job not found."}, status_code=404)
    # Defensive: ensure no PN field leaks even if get_lookup_job_public is
    # ever modified — explicitly strip anything that smells like a PN.
    for forbidden in ("primary_pn", "alt_pns_json", "alt_pns", "dealer_url", "vin"):
        job.pop(forbidden, None)
    return JSONResponse(job)


@app.get("/lookup/{job_id}", response_class=HTMLResponse)
async def public_lookup_status_page(job_id: str) -> HTMLResponse:
    """Direct landing page (e.g., from the result-ready email) — shows
    the same paywall UI keyed to this job. Browser-side JS will poll
    status and render either the paywall or unverified panel."""
    job = db.get_lookup_job_public(job_id)
    if not job:
        return _render("home_public.html")
    # Just render the home page; the JS will fetch job status and adjust UI.
    # We prefill the job_id via a meta tag.
    html = (TEMPLATE_DIR / "home_public.html").read_text(encoding="utf-8")
    inject = (
        f'<meta name="lbt1-resume-job-id" content="{job_id}">\n'
        '<script>window.__LBT1_RESUME_JOB_ID__ = "' + job_id + '";</script>\n'
    )
    html = html.replace("</head>", inject + "</head>", 1)
    return HTMLResponse(html)


@app.get("/buy/single")
async def buy_single(request: Request, job_id: str = "") -> Response:
    """Start a Stripe Checkout session for a $7.99 single-VIN unlock.
    The job_id is propagated through metadata so the webhook can
    flip paid_at and redirect the user to the result reveal."""
    return await _create_buy_session(
        request, job_id=job_id, kind="single",
        amount_cents=799, credits=1, product_name="Locksmith Daddy — single VIN unlock",
    )


@app.get("/buy/ten")
async def buy_ten(request: Request, job_id: str = "") -> Response:
    """Start a Stripe Checkout session for a $49 / 10-VIN bundle.
    If a job_id is provided, that single VIN is unlocked immediately
    AND 9 additional credits are granted to the user (or to a
    temporary credit pool tied to the job until they create an account)."""
    return await _create_buy_session(
        request, job_id=job_id, kind="ten",
        amount_cents=4900, credits=10, product_name="Locksmith Daddy — 10-pack VIN unlocks",
    )


async def _create_buy_session(
    request: Request, *, job_id: str, kind: str,
    amount_cents: int, credits: int, product_name: str,
) -> Response:
    if not stripe_client.is_enabled():
        return HTMLResponse(
            "<h2>Payments are not configured on this deploy.</h2>"
            "<p>Email <a href='mailto:cetabo.contact@gmail.com'>cetabo.contact@gmail.com</a> "
            "to unlock your result manually.</p>",
            status_code=503,
        )
    base = config.BASE_URL.rstrip("/")
    metadata = {"kind": kind, "credits": str(credits)}
    customer_email = None
    if job_id:
        job = db.get_lookup_job_public(job_id)
        if not job:
            return HTMLResponse("Job not found.", status_code=404)
        metadata["job_id"] = job_id
        # Pull the captured email from the job to prefill checkout
        with db.get_db() as d:
            row = d.execute("SELECT email FROM lookup_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row and row["email"]:
                customer_email = row["email"]

    db.record_pending_purchase(
        stripe_session_id=f"pending-{job_id or 'no-job'}-{kind}",  # placeholder until session created
        pack_kind=kind, credits=credits, amount_cents=amount_cents,
        customer_email=customer_email,
    )

    success_url = (
        f"{base}/result/{job_id}?paid=1"
        if job_id else f"{base}/?bundle_purchased=1"
    )
    cancel_url = (
        f"{base}/lookup/{job_id}?cancelled=1"
        if job_id else f"{base}/?cancelled=1"
    )
    checkout_url = stripe_client.create_one_time_checkout(
        amount_cents=amount_cents,
        product_name=product_name,
        quantity=1,
        success_url=success_url,
        cancel_url=cancel_url,
        metadata=metadata,
        customer_email=customer_email,
    )
    if not checkout_url:
        return HTMLResponse(
            "Could not create checkout session. Please email "
            "<a href='mailto:cetabo.contact@gmail.com'>cetabo.contact@gmail.com</a>.",
            status_code=502,
        )
    return RedirectResponse(checkout_url, status_code=status.HTTP_303_SEE_OTHER)


@app.get("/result/{job_id}", response_class=HTMLResponse)
async def public_result(job_id: str, paid: int = 0) -> HTMLResponse:
    """Reveal page. Only renders the PN if paid_at is set on the job."""
    result = db.get_lookup_job_paid_result(job_id)
    if not result:
        # Either job doesn't exist or it's unpaid. Surface a clear message.
        job = db.get_lookup_job_public(job_id)
        if not job:
            return _render("home_public.html")
        if job.get("status") == "verified" and not job.get("paid"):
            return HTMLResponse(
                "<!doctype html><html><body style='font-family: system-ui; max-width: 540px; "
                "margin: 80px auto; padding: 20px; background: #0f1419; color: #e6edf3;'>"
                "<h2>Payment required to unlock this result.</h2>"
                f"<p><a style='color:#ff6b35;' href='/buy/single?job_id={job_id}'>"
                "Pay $7.99 to unlock →</a></p>"
                "</body></html>",
                status_code=402,
            )
        return _render("home_public.html")

    vehicle_label = " ".join(
        str(x) for x in [
            result.get("vehicle_year"), result.get("vehicle_make"),
            result.get("vehicle_model"), result.get("vehicle_trim"),
        ] if x
    )
    alt_pns = result.get("alt_pns") or []
    alt_html = ""
    if alt_pns:
        items = "".join(f"<li>{pn}</li>" for pn in alt_pns)
        alt_html = (
            "<div style='margin-top:14px;'>"
            "<div style='font-size:12px;color:#8b949e;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px;'>"
            "Alternates the dealer also lists for this vehicle"
            "</div>"
            f"<ul class='alt-list'>{items}</ul>"
            "</div>"
        )
    paid_at = result.get("paid_at") or ""
    create_account_html = (
        "<div class='upsell'>"
        "<h3>Save these results to a free account?</h3>"
        "<p>Re-access this PN anytime from your dashboard. Takes 20 seconds. State / locksmith license not required.</p>"
        f"<div class='row'><button class='ten' onclick=\"window.location.href='/signup?attach_job={job_id}'\">Create account</button>"
        "<button class='free' onclick=\"window.location.href='/'\">Maybe later</button></div></div>"
    )

    return _render(
        "result_reveal.html",
        vehicle_label=vehicle_label,
        vin=result.get("vin", ""),
        primary_pn=result.get("primary_pn", ""),
        dealer_url=result.get("dealer_url") or "#",
        alt_pns_html=alt_html,
        paid_at_display=paid_at[:10] if paid_at else "today",
        create_account_html=create_account_html,
    )


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
