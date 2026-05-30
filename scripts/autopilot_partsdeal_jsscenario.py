"""Next-AM-session script: use ScrapFly's `js_scenario` to render the
toyotapartsdeal.com homepage, fill the VIN input, click search, and
capture the redirect URL.

The redirect URL contains the resolved vehicle slug (e.g.
`/parts/2024-toyota-camry-se/...`) which we can then scrape directly
without needing the API at all.

This is the simplest path around the Site:不存在 blocker — we let the
JS do the work and observe the result.

Cost target: ~50-100 credits per probe ($0.013-0.02).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

env_path = Path(__file__).resolve().parents[1] / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("SCRAPFLY_KEY="):
            os.environ["SCRAPFLY_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
            break

API_KEY = os.environ["SCRAPFLY_KEY"]
SCRAPFLY = "https://api.scrapfly.io/scrape"

TESTS = [
    ("www.toyotapartsdeal.com", "4T1G11AK6R0123456"),
    ("www.hyundaipartsdeal.com", "5NPD84LFXHH074817"),
    ("www.kiapartsnow.com", "5XYK6CDF8TG390982"),
]


async def probe(client: httpx.AsyncClient, host: str, vin: str) -> dict:
    print("=" * 90)
    print(f"{host}  VIN={vin}")

    # Build js_scenario: find VIN input, type the VIN, find search button,
    # click it, wait for navigation. Then return whatever URL we ended up on.
    js_scenario = json.dumps([
        {"wait_for_selector": {"selector": "input[placeholder*='VIN']",
                                 "timeout": 15000}},
        {"fill": {"selector": "input[placeholder*='VIN']",
                    "value": vin, "clear": True}},
        # Various button selectors to try
        {"click": {"selector": "button[type='submit']", "ignore_missing": True}},
        {"click": {"selector": "input[type='submit']", "ignore_missing": True}},
        {"click": {"selector": "[class*='vin'][class*='button']",
                    "ignore_missing": True}},
        # Wait for any navigation / network completion
        {"wait_for_navigation": {"timeout": 15000}},
    ])

    params = {
        "key": API_KEY,
        "url": f"https://{host}/",
        "country": "us",
        "asp": "true",
        "render_js": "true",
        "js_scenario": js_scenario,
        "screenshot_flags": "stabilize",
    }
    try:
        r = await client.get(SCRAPFLY, params=params, timeout=180)
    except Exception as exc:
        print(f"  EXCEPTION: {exc}")
        return {"host": host, "ok": False, "exc": str(exc)}
    try:
        env = r.json()
    except Exception:
        print(f"  raw HTTP {r.status_code} body[:300]={r.text[:300]}")
        return {"host": host, "ok": False, "http": r.status_code}

    result = env.get("result") or {}
    status = result.get("status_code")
    final_url = result.get("url")
    content = result.get("content", "") or ""
    print(f"  upstream: status={status}  final_url={final_url}")
    print(f"  content len: {len(content)}")

    # If we navigated to a vehicle-specific URL, we win
    # Save the resulting HTML for offline inspection
    out = Path(__file__).resolve().parents[1] / "data" / "runs" / f"jsscenario_{host}.html"
    out.write_text(content[:200000], encoding="utf-8")
    print(f"  saved: {out}")
    return {"host": host, "ok": status == 200, "final_url": final_url,
             "status": status}


async def main() -> None:
    async with httpx.AsyncClient() as client:
        for host, vin in TESTS:
            await probe(client, host, vin)


if __name__ == "__main__":
    asyncio.run(main())
