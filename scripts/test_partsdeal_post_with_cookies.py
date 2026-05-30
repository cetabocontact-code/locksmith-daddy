"""Replay POST /api/url/vehicle-redirect with the freshly-captured cookies.
The session must be initialized by a homepage visit first — that's how the
backend ties the request to the correct site context."""

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

# Test on all 3 sites — confirms the multi-tenant approach works
TESTS = [
    {
        "host": "www.toyotapartsdeal.com",
        "vin": "4T1G11AK6R0123456",  # 2024 Camry SE
    },
    {
        "host": "www.hyundaipartsdeal.com",
        "vin": "5NPD84LFXHH074817",  # 2017 Elantra — known real VIN
    },
    {
        "host": "www.kiapartsnow.com",
        "vin": "5XYK6CDF8TG390982",  # 2026 Sportage X-Line
    },
]


async def run_for_site(client: httpx.AsyncClient, host: str, vin: str) -> None:
    print("=" * 90)
    print(f"Site: {host}  VIN: {vin}")

    # STEP 1: visit homepage via ScrapFly to get a session cookie
    print("  Step 1: visiting homepage to capture session cookie")
    r = await client.get(SCRAPFLY, params={
        "key": API_KEY,
        "url": f"https://{host}/",
        "country": "us",
        "asp": "true",
        "render_js": "false",
    }, timeout=60)
    env = r.json()
    result = env.get("result") or {}
    cookies = result.get("cookies") or []
    # Build cookie string
    cookie_jar = "; ".join(f"{c['name']}={c['value']}" for c in cookies
                            if c.get("name") and c.get("value"))
    print(f"    cookies captured: {[c['name'] for c in cookies]}")
    print(f"    cookie_jar: {cookie_jar[:200]}...")

    # STEP 2: POST /api/url/vehicle-redirect with cookies + Origin/Referer
    print(f"  Step 2: POST /api/url/vehicle-redirect with session cookies")
    headers_to_send = {
        "Content-Type": "application/json; charset=utf-8",
        "Origin": f"https://{host}",
        "Referer": f"https://{host}/",
        "Accept": "application/json, text/plain, */*",
        "Cookie": cookie_jar,
    }
    params = {
        "key": API_KEY,
        "url": f"https://{host}/api/url/vehicle-redirect",
        "country": "us",
        "asp": "true",
        "render_js": "false",
        "method": "POST",
    }
    for k, v in headers_to_send.items():
        params[f"headers[{k}]"] = v
    body = json.dumps({"vin": vin}).encode("utf-8")
    r2 = await client.post(SCRAPFLY, params=params,
                            content=body,
                            headers={"Content-Type": "application/json"},
                            timeout=60)
    try:
        env2 = r2.json()
        result2 = env2.get("result") or {}
        status = result2.get("status_code")
        content = result2.get("content", "")
        print(f"    upstream status: {status}  content[:500]: {content[:500]}")
    except Exception as exc:
        print(f"    parse error: {exc}; raw[:400]: {r2.text[:400]}")


async def main() -> None:
    async with httpx.AsyncClient() as client:
        for t in TESTS:
            await run_for_site(client, t["host"], t["vin"])


if __name__ == "__main__":
    asyncio.run(main())
