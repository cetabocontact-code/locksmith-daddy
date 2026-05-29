"""ScrapFly budget governor — daily cap + 50%/90% alerts.

Plan: Discovery (200k credits/month), resets monthly. Per user 2026-05-29:
- 50% threshold (100k used): notify
- 90% threshold (180k used): critical, drop diagnostic burn to <500/day
- Hard stop at 95% to leave headroom for user lookups

State is persisted in data/budget_state.json so the dispatcher survives
restarts.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from lbt1 import config

STATE_PATH = Path(config.DATA_DIR) / "budget_state.json"

# Discovery plan
MONTHLY_CAP = 200_000
ALERT_50_PCT = 100_000
ALERT_90_PCT = 180_000
HARD_STOP_PCT = 190_000  # leave 5% for user lookups in flight

# Period boundaries (Discovery resets monthly per signup date — user is on
# 28th of each month per ScrapFly dashboard 2026-05-29)
RESET_DAY = 28


def _next_reset() -> date:
    """Compute next ScrapFly reset date (28th of next month)."""
    today = date.today()
    if today.day < RESET_DAY:
        return date(today.year, today.month, RESET_DAY)
    if today.month == 12:
        return date(today.year + 1, 1, RESET_DAY)
    return date(today.year, today.month + 1, RESET_DAY)


def _fetch_live_status() -> dict[str, Any] | None:
    """Hit ScrapFly /account to get authoritative credit usage. Falls back
    to local state on error. Best-effort."""
    key = os.environ.get("SCRAPFLY_KEY") or os.environ.get("SCRAPFLY_API_KEY", "")
    if not key:
        return None
    try:
        with httpx.Client(timeout=10) as client:
            r = client.get("https://api.scrapfly.io/account", params={"key": key})
            if r.status_code != 200:
                return None
            data = r.json()
            sub = data.get("subscription", {})
            scrape = sub.get("usage", {}).get("scrape", {})
            return {
                "used": int(scrape.get("current", 0)),
                "limit": int(scrape.get("limit", MONTHLY_CAP)),
                "remaining": int(scrape.get("remaining", 0)),
                "period_end": sub.get("period", {}).get("end"),
            }
    except Exception:
        return None


def current_status() -> dict[str, Any]:
    """Get current ScrapFly status (used, remaining, %, days to reset)."""
    live = _fetch_live_status()
    if live:
        used = live["used"]
        cap = live["limit"]
    else:
        # Fallback: load from local state file
        used = 0
        cap = MONTHLY_CAP
        if STATE_PATH.exists():
            try:
                d = json.loads(STATE_PATH.read_text(encoding="utf-8"))
                used = int(d.get("estimated_used", 0))
            except Exception:
                pass
    remaining = max(0, cap - used)
    used_pct = (used / cap * 100) if cap else 0
    days_to_reset = (_next_reset() - date.today()).days
    return {
        "used": used, "cap": cap, "remaining": remaining,
        "used_pct": used_pct, "days_to_reset": days_to_reset,
        "live_data": live is not None,
    }


def allow_burn(estimated_credits: int) -> bool:
    """Gate before kicking off a session that will burn N credits.
    Returns False if we'd cross the hard-stop threshold."""
    s = current_status()
    return (s["used"] + estimated_credits) < HARD_STOP_PCT


def log_status_snapshot() -> None:
    """Write today's status to data/budget_state.json (for trend tracking).
    Emit threshold alerts to stdout when crossing 50% or 90%."""
    s = current_status()
    prev_used = 0
    if STATE_PATH.exists():
        try:
            prev = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            prev_used = int(prev.get("used", 0))
        except Exception:
            pass

    if prev_used < ALERT_50_PCT <= s["used"]:
        print(f"[BUDGET ALERT 50%] ScrapFly usage crossed 100k credits "
              f"(current: {s['used']}, resets in {s['days_to_reset']} days)")
    if prev_used < ALERT_90_PCT <= s["used"]:
        print(f"[BUDGET ALERT 90%] ScrapFly usage crossed 180k credits — "
              f"diagnostic burn must drop below 500/day. "
              f"(current: {s['used']}, resets in {s['days_to_reset']} days)")

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({
        "snapshot_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "used": s["used"], "cap": s["cap"], "remaining": s["remaining"],
        "used_pct": s["used_pct"], "days_to_reset": s["days_to_reset"],
    }, indent=2), encoding="utf-8")
