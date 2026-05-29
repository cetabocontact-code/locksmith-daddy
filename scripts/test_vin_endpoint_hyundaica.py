"""POST to /wm.aspx/CreateVinLinks on parts.hyundaicanada.com with the
problem VIN. The response (in classic ASMX {"d": ...} envelope) should
contain a URL or vehicle-identification result.

If this works → we have a real fallback path for 2026+ Hyundai when the
US Revolution Parts feed lacks data.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["LBT1_SCRAPE_BACKEND"] = "scrapfly"

from lbt1.scrapers.backends import get_backend  # noqa: E402

VINS = [
    "KMHLM4DG3TU122912",  # the user's case
    "KMHLS4DG5TU123100",  # the original failing case
    "5XYK6CDF8TG390982",  # 2026 Kia Sportage (not Hyundai — should return empty/error here)
]

CANADA_ENDPOINT = "https://parts.hyundaicanada.com/wm.aspx/CreateVinLinks"
USA_KIA_ENDPOINT = "https://parts.kia.com/wm.aspx/CreateVinLinks"


async def call(backend, endpoint: str, vin: str) -> None:
    print("=" * 100)
    print(f"POST {endpoint}  vin={vin}")
    body = json.dumps({
        "VinNumber": vin,
        "AbsolutePath": quote("/default.aspx"),
        "QueryString": "",
    })
    # Try via backend's POST capability. ScrapFly supports POST + Content-Type.
    try:
        r = await backend.fetch(
            endpoint,
            method="POST",
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            },
            data=body,
        )
    except TypeError:
        # Backend may not support POST kwargs that way; fallback signature
        try:
            r = await backend.fetch(endpoint, method="POST", body=body)
        except Exception as exc:  # noqa: BLE001
            print(f"  Backend POST not supported: {exc}")
            return
    print(f"  status={r.status}  final={r.final_url}  len={len(r.html or '')}")
    if r.error:
        print(f"  error: {r.error[:300]}")
    body_text = (r.html or "")[:1500]
    print(f"  body[:1500]:\n    {body_text}")


async def main() -> None:
    backend = get_backend()
    try:
        # Test Hyundai Canada with both 2026 Elantra VINs
        for vin in VINS[:2]:
            await call(backend, CANADA_ENDPOINT, vin)
        # Test US Kia parts catalog with a Kia VIN
        await call(backend, USA_KIA_ENDPOINT, VINS[2])
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
