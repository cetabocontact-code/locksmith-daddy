"""Debug: directly harvest Kia 2022 Telluride RELAY--MODULE to see why
the driver missed 95440S9330. Earlier probe showed 42 parts on this page
including the FOB-SMART KEY.
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

URLS = [
    # The URL my driver visited (canonical path)
    "https://parts.kia.com/a/Kia_2022_Telluride-38L-AT-4WD-SX/_92860_11087120/RELAY--MODULE/AKMAPS919_91-952.html",
]


async def main() -> None:
    backend = get_backend()
    try:
        for url in URLS:
            print("=" * 100)
            print(url)
            r = await backend.fetch(url)
            print(f"  status={r.status}  final={r.final_url}  len={len(r.html or '')}")
            if not r.ok or r.error:
                print(f"  error: {r.error[:200]}")
                continue

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.html, "lxml")
            # All /p/ links
            seen = set()
            parts = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                m = re.match(r"/p/[^/]+/([^/]+)/\d+/([^.?]+)\.html", href)
                if not m:
                    continue
                if href in seen:
                    continue
                seen.add(href)
                name = m.group(1).replace("-", " ")
                pn = m.group(2)
                txt = a.get_text(" ", strip=True)[:80]
                parts.append((pn, name, txt, href))

            print(f"  total /p/ links: {len(parts)}")
            for pn, name, txt, href in parts[:50]:
                marker = ""
                if pn.startswith(("95440", "95430", "95431", "95441", "95442", "95446")):
                    marker = "  <<<FOB FAMILY"
                elif any(k in (name + txt).lower() for k in (
                    "fob", "smart key", "smart-key", "smartkey", "transmitter",
                    "keyless", "remote", "transponder", "immobilizer", "anti-theft",
                )):
                    marker = "  <<<NAME HIT"
                print(f"    pn={pn!r:25s} name={name!r:60s}{marker}")
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
