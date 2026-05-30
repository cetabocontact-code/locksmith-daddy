"""Extract the VIN-search POST handler from toyotapartsdeal.com's
pages-BaseHome.js — `byVinHidden` is the JS variable that holds the
VIN. Find the function that POSTs it to /api/url/vehicle-redirect."""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["LBT1_SCRAPE_BACKEND"] = "scrapfly"

from lbt1.scrapers.backends import get_backend  # noqa: E402

URL = "https://www.toyotapartsdeal.com/js/pages-BaseHome.js?v=2026052803"


async def main() -> None:
    backend = get_backend()
    try:
        r = await backend.fetch(URL)
        body = r.html or ""
        print(f"length: {len(body)}")

        # Find every occurrence of "byVinHidden" and show 600 chars of context
        for m in re.finditer(r"byVinHidden", body):
            i = m.start()
            ctx = body[max(0, i-300):i+600]
            print("=" * 90)
            print(f"@offset {i}")
            print(ctx)

        # Also find the POST call to /api/url/vehicle-redirect and show context
        print("\n" + "=" * 90)
        print("vehicle-redirect call context")
        print("=" * 90)
        for m in re.finditer(r"vehicle-redirect", body):
            i = m.start()
            ctx = body[max(0, i-400):i+400]
            print(ctx)
            print("---")
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
