"""Probe Toyota Camry SE 2024 keyless-entry category to see how Toyota
names key parts (Hyundai uses 'Transmitter' / 'Fob Smart Key' but Toyota
likely uses different terms). Identifies which keywords we need to add
to _is_key_part / classify_part_name.

Cost: ~$0.04 (3 category pages).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["LBT1_SCRAPE_BACKEND"] = "scrapfly"

from lbt1.scrapers.backends import get_backend  # noqa: E402

VEHICLE = "https://toyota.oempartsonline.com/v-2024-toyota-camry--se--2-5l-l4-gas"
URLS = [
    f"{VEHICLE}/electrical--keyless-entry-components",
    f"{VEHICLE}/electrical--anti-theft-system",
    f"{VEHICLE}",  # vehicle landing page — see ALL category links
]


async def main() -> None:
    backend = get_backend()
    try:
        for url in URLS:
            print("=" * 90)
            print(url)
            r = await backend.fetch(url)
            print(f"  status={r.status}  final={r.final_url}  len={len(r.html or '')}")
            if not r.ok:
                continue
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.html, "lxml")
            title = (soup.title.string or "").strip() if soup.title else ""
            print(f"  title: {title[:140]}")
            # Marketplace cards (parts)
            cards = soup.select(".marketplace-info-col")
            print(f"  parts cards: {len(cards)}")
            for c in cards[:15]:
                name = c.select_one(".product-title a")
                pn = c.select_one(".product-partnum a")
                desc = c.select_one(".contextual_description")
                print(f"    pn={pn.get_text(strip=True) if pn else '?':18s} "
                      f"name={(name.get_text(strip=True) if name else '?')[:55]:55s} "
                      f"desc={(desc.get_text(strip=True) if desc else '')[:40]}")
            # If this is the vehicle landing page, show category sub-paths
            if url.endswith("--2-5l-l4-gas"):
                from urllib.parse import urlparse
                links = soup.find_all("a", href=True)
                seen = set()
                key_links = []
                for a in links:
                    href = a["href"]
                    if VEHICLE.split("//", 1)[1] in href and "/electrical" in href.lower():
                        if href in seen:
                            continue
                        seen.add(href)
                        key_links.append((a.get_text(strip=True)[:50], href))
                print(f"\n  ALL electrical sub-paths exposed on vehicle page:")
                for txt, href in key_links[:25]:
                    print(f"    {txt:50s} -> {href[-80:]}")
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
