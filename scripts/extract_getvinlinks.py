"""Extract the GetVinLinks function definition from parts.hyundaicanada.com's
JS bundles. It's the function that posts the VIN to the backend — once we know
its endpoint we can build a HyundaiCanadaDriver.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["LBT1_SCRAPE_BACKEND"] = "scrapfly"

from lbt1.scrapers.backends import get_backend  # noqa: E402

BUNDLES = [
    "https://parts.hyundaicanada.com/bundles/legacy?v=-FF1qepHHVHMer4xbG0e1-mHNlUEt5gczhHuYo3DVQs1",
    "https://parts.hyundaicanada.com/bundles/app?v=rvkS5fFL0CMPfB8XQ6GiLUUlKg--ottXExUaUgPWtJs1",
    "https://parts.hyundaicanada.com/scripts/global.js?v-639154041120000000",
]


async def main() -> None:
    backend = get_backend()
    try:
        for url in BUNDLES:
            print("=" * 100)
            print(url)
            r = await backend.fetch(url)
            if not r.ok:
                print(f"  failed: status={r.status} err={r.error}")
                continue
            body = r.html or ""
            print(f"  length: {len(body)}")

            # Search for GetVinLinks function or AJAX patterns
            for pattern in (
                r"function\s+GetVinLinks[^}]{0,2000}",
                r"GetVinLinks\s*[:=]\s*function[^}]{0,2000}",
                # ASMX-style call
                r'\.asmx/[A-Za-z]+',
                r'/services/[\w/]+',
                r"url\s*:\s*['\"][^'\"]*[Vv]in[^'\"]*['\"]",
                # Generic AJAX url for VIN
                r'["\'][^"\']*[Vv]in[Ll]inks[^"\']*["\']',
                r'["\'][^"\']*Get[Vv]in[^"\']*["\']',
            ):
                for m in re.finditer(pattern, body, re.MULTILINE):
                    snippet = m.group(0)[:600].replace("\n", "\n      ")
                    print(f"  [PATTERN {pattern[:40]}]")
                    print(f"      {snippet}")

            # Also dump any /api/ or /services/ paths
            paths = set(re.findall(r'["\'](/[\w\-./%]+\.(?:asmx|aspx|svc|json)(?:/\w+)?)["\']', body))
            if paths:
                print(f"  ASP.NET-style endpoints found:")
                for p in sorted(paths):
                    print(f"    {p}")
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
