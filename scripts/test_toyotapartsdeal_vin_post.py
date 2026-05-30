"""Test the discovered POST /api/url/vehicle-redirect endpoint on
toyotapartsdeal.com. Try multiple body shapes to find the right one.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["LBT1_SCRAPE_BACKEND"] = "scrapfly"

from lbt1.scrapers.backends import get_backend  # noqa: E402

URL = "https://www.toyotapartsdeal.com/api/url/vehicle-redirect"
VIN = "4T1G11AK6R0123456"  # valid checksum 2024 Camry SE

BODY_SHAPES = [
    {"vin": VIN},
    {"VIN": VIN},
    {"vinNumber": VIN},
    {"vin_number": VIN},
    {"vehicleVin": VIN},
    {"vinSearch": VIN},
    {"search": VIN},
    # Some sites wrap inside a `data` object
    {"data": {"vin": VIN}},
]


async def main() -> None:
    backend = get_backend()
    try:
        for body in BODY_SHAPES:
            print("=" * 90)
            print(f"POST {URL}")
            print(f"  body: {json.dumps(body)}")
            try:
                r = await backend.fetch_json_post(
                    URL,
                    json_body=body,
                    headers={
                        "Origin": "https://www.toyotapartsdeal.com",
                        "Referer": "https://www.toyotapartsdeal.com/",
                    },
                )
            except Exception as exc:
                print(f"  EXCEPTION: {type(exc).__name__}: {exc}")
                continue
            print(f"  status={r.status}  len={len(r.html or '')}")
            content = r.html or ""
            if content:
                print(f"  body[:500]: {content[:500]}")
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
