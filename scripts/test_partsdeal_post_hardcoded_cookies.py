"""Use the cookies captured by the JS render earlier — hardcoded — to see
if the session is reusable across requests (no JS needed if so)."""

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

# Hardcoded cookies from the previous JS-rendered probe
COOKIE_JARS = {
    "www.toyotapartsdeal.com":
        "CartTotal=0; GuidNew=8b263aa3-15dc-405c-aaae-cbf73a55f501; "
        "cookiesession1=678A3E0D8FE3CD589E07923E1B4EB339",
    "www.hyundaipartsdeal.com":
        "CartTotal=0; GuidNew=ebc0008f-1e6c-48fb-9809-55c0f2e49457; "
        "cookiesession1=678A3E0D973E902B4D0E998B8B1FDFF2",
    "www.kiapartsnow.com":
        "CartTotal=0; GuidNew=a6b38648-4bd2-46fe-a250-ea5920e87c80; "
        "cookiesession1=678A3E0D0BC12FE31BC8650F12D05DBA",
}

TESTS = [
    ("www.toyotapartsdeal.com", "4T1G11AK6R0123456"),
    ("www.hyundaipartsdeal.com", "5NPD84LFXHH074817"),
    ("www.kiapartsnow.com", "5XYK6CDF8TG390982"),
]


async def try_post(client: httpx.AsyncClient, host: str, vin: str,
                    extra_headers: dict | None = None) -> None:
    cookie_jar = COOKIE_JARS[host]
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Origin": f"https://{host}",
        "Referer": f"https://{host}/",
        "Accept": "application/json, text/plain, */*",
        "Cookie": cookie_jar,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    if extra_headers:
        headers.update(extra_headers)
    params = {
        "key": API_KEY,
        "url": f"https://{host}/api/url/vehicle-redirect",
        "country": "us",
        "asp": "true",
        "render_js": "false",
        "method": "POST",
    }
    for k, v in headers.items():
        params[f"headers[{k}]"] = v
    body = json.dumps({"vin": vin}).encode("utf-8")
    r = await client.post(SCRAPFLY, params=params, content=body,
                            headers={"Content-Type": "application/json"},
                            timeout=60)
    try:
        env = r.json()
        result = env.get("result") or {}
        status = result.get("status_code")
        content = result.get("content", "")
        print(f"    upstream {status}  body: {content[:400]}")
    except Exception as exc:
        print(f"    error: {exc}")


async def main() -> None:
    async with httpx.AsyncClient() as client:
        for host, vin in TESTS:
            print("=" * 90)
            print(f"\n{host}  VIN={vin}")

            # Variation 1: just cookies + Origin + Referer
            print("  V1: cookies + Origin + Referer")
            await try_post(client, host, vin)

            # Variation 2: + X-Requested-With (common AJAX marker)
            print("  V2: + X-Requested-With")
            await try_post(client, host, vin,
                            {"X-Requested-With": "XMLHttpRequest"})

            # Variation 3: + Host header explicitly
            print("  V3: + Host header")
            await try_post(client, host, vin, {"Host": host})


if __name__ == "__main__":
    asyncio.run(main())
