"""Search for Toyota fob PN family (89070) on toyota.oempartsonline.com.
The search result shows each PN's category breadcrumb — tells us
exactly where fobs are filed.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["LBT1_SCRAPE_BACKEND"] = "scrapfly"

from lbt1.scrapers.backends import get_backend  # noqa: E402

URLS = [
    "https://toyota.oempartsonline.com/search?search_str=89070",
    "https://toyota.oempartsonline.com/search?search_str=89904",
]


async def main() -> None:
    backend = get_backend()
    try:
        for url in URLS:
            print("=" * 90)
            print(url)
            r = await backend.fetch(url)
            print(f"  status={r.status}  final={r.final_url}")
            if not r.ok:
                continue
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.html, "lxml")
            cards = soup.select(".marketplace-info-col")
            print(f"  cards: {len(cards)}")
            # Each card has a PN + an "in category" link / breadcrumb
            for c in cards[:10]:
                pn_el = c.select_one(".product-partnum a")
                name_el = c.select_one(".product-title a")
                if not pn_el:
                    continue
                pn = pn_el.get_text(strip=True)
                name = name_el.get_text(strip=True) if name_el else ""
                # Look for category link inside the card
                cat_text = ""
                for a in c.find_all("a", href=True):
                    href = a["href"]
                    if "/v-" in href and "--" in href.split("/")[-1]:
                        cat_text = a.get_text(" ", strip=True) + "  " + href[-80:]
                        break
                print(f"    pn={pn:18s}  name={name[:30]:30s}  cat={cat_text[:90]}")

            # Look at where the search FILTER suggests parts live
            print(f"  Filter-by-category suggestions:")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/c-" in href or "category" in href.lower():
                    txt = a.get_text(" ", strip=True)[:50]
                    if txt and "category" in href.lower() or "/c-" in href:
                        print(f"    {txt:40s}  {href[-80:]}")
                        break
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
