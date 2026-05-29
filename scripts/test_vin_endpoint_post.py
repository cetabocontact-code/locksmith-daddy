"""Direct POST to /wm.aspx/CreateVinLinks via ScrapFly's HTTP API. The
existing backend wrapper only does GET, so we call ScrapFly directly to
prove the endpoint works before building a proper driver.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Pull SCRAPFLY_KEY from .env
env_path = Path(__file__).resolve().parents[1] / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("SCRAPFLY_KEY="):
            os.environ["SCRAPFLY_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
            break

API_KEY = os.environ["SCRAPFLY_KEY"]


VINS = [
    "KMHLM4DG3TU122912",  # 2026 Elantra SEL Sport / Sport Plus
    "KMHLS4DG5TU123100",  # 2026 Elantra SEL Sport Premium
    "5NPD84LFXHH074817",  # 2017 Elantra SE - baseline (works in US)
    "KMHC85LH3MU082134",  # 2021 Ioniq Hybrid - baseline
]
KIA_VINS = [
    "5XYK6CDF8TG390982",  # 2026 Sportage X-Line - works in US Revolution Parts
    "5XYP5DHC5NG256061",  # 2022 Telluride SX - baseline
]


async def call(client: httpx.AsyncClient, host: str, vin: str) -> None:
    target = f"https://{host}/wm.aspx/CreateVinLinks"
    body_obj = {
        "VinNumber": vin,
        "AbsolutePath": quote("/default.aspx"),
        "QueryString": "",
    }
    print("=" * 100)
    print(f"POST {target}  vin={vin}")
    # ScrapFly: POST to /scrape, JSON body goes in request body. Headers
    # set via headers[...] params.
    r = await client.post(
        "https://api.scrapfly.io/scrape",
        params={
            "key": API_KEY,
            "url": target,
            "method": "POST",
            "asp": "true",
            "render_js": "false",
            "headers[Content-Type]": "application/json; charset=utf-8",
            "headers[X-Requested-With]": "XMLHttpRequest",
            "headers[Accept]": "application/json, text/javascript, */*; q=0.01",
            "headers[Origin]": f"https://{host}",
            "headers[Referer]": f"https://{host}/",
        },
        content=json.dumps(body_obj).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        timeout=90,
    )
    try:
        env = r.json()
    except Exception:
        print(f"  HTTP {r.status_code}  body[:600]={r.text[:600]}")
        return

    result = env.get("result") or {}
    print(f"  upstream status: {result.get('status_code')}  url: {result.get('url')}")
    headers_resp = result.get("response_headers") or {}
    print(f"  upstream content-type: {headers_resp.get('content-type') or headers_resp.get('Content-Type')}")
    content = result.get("content") or ""
    print(f"  content len: {len(content)}")
    print(f"  content[:1500]:\n    {content[:1500]}")


async def main() -> None:
    async with httpx.AsyncClient() as client:
        # Hyundai Canada — 2 problem 2026 VINs + 2 baselines that work in US
        print("\n##### Hyundai Canada (parts.hyundaicanada.com) #####")
        for vin in VINS:
            await call(client, "parts.hyundaicanada.com", vin)
        # Kia US official — has the VIN catalog and uses same platform
        print("\n##### Kia US Official (parts.kia.com) #####")
        for vin in KIA_VINS:
            await call(client, "parts.kia.com", vin)
        # Hyundai US Official — see if it's reachable now
        print("\n##### Hyundai US Official (parts.hyundaiusa.com) #####")
        for vin in [VINS[0], VINS[2]]:
            await call(client, "parts.hyundaiusa.com", vin)


if __name__ == "__main__":
    asyncio.run(main())
