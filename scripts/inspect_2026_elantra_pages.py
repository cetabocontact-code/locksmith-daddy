"""Inspect the actual category page HTML for the 2026 Elantra SEL Sport Premium
on BOTH dealer sites to determine if the catalog is genuinely empty or if our
parser is missing parts.

If the page truly has no parts, the fallback chain has done all it can — the
catalog itself doesn't have the data yet. If parts ARE listed but our parser
misses them, that's a bug we need to fix.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["LBT1_SCRAPE_BACKEND"] = "scrapfly"

from lbt1.scrapers.backends import get_backend  # noqa: E402


PAGES = [
    # Primary
    "https://hyundai.oempartsonline.com/v-2026-hyundai-elantra--sel-sport-premium--2-0l-l4-gas/electrical--keyless-entry-components",
    "https://hyundai.oempartsonline.com/v-2026-hyundai-elantra--sel-sport-premium--2-0l-l4-gas/electrical--anti-theft-system",
    # Fallback
    "https://www.hyundaioempart.com/v-2026-hyundai-elantra--sel-sport-premium--2-0l-l4-gas/electrical--keyless-entry-components",
    "https://www.hyundaioempart.com/v-2026-hyundai-elantra--sel-sport-premium--2-0l-l4-gas/electrical--anti-theft-system",
    # Also probe the simpler trim-less URL — some catalogs key parts at model level
    "https://www.hyundaioempart.com/v-2026-hyundai-elantra/electrical--keyless-entry-components",
    "https://hyundai.oempartsonline.com/v-2026-hyundai-elantra/electrical--keyless-entry-components",
]


async def main() -> None:
    backend = get_backend()
    try:
        for url in PAGES:
            print("=" * 100)
            print(url)
            r = await backend.fetch(url)
            print(f"  status={r.status}  final={r.final_url}  htmllen={len(r.html or '')}")
            if r.error:
                print(f"  error={r.error[:200]}")
                continue

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.html, "lxml")
            title = (soup.title.string or "").strip() if soup.title else ""
            print(f"  title: {title[:160]}")

            cards = soup.select(".marketplace-info-col")
            print(f"  .marketplace-info-col cards: {len(cards)}")

            # Show all product titles + PNs found on the page
            for i, c in enumerate(cards[:25]):
                name_el = c.select_one(".product-title a") or c.select_one(".product-title")
                pn_el = c.select_one(".product-partnum a") or c.select_one(".product-partnum")
                name = name_el.get_text(strip=True) if name_el else None
                pn = pn_el.get_text(strip=True) if pn_el else None
                print(f"    [{i:2d}] name={name!r}  pn={pn!r}")

            # Also check for "no results" / "we don't have" messaging
            text = soup.get_text(" ", strip=True).lower()
            for needle in (
                "no results", "no products", "we don't have", "we do not have",
                "not available", "no parts found", "currently no",
            ):
                if needle in text:
                    idx = text.find(needle)
                    print(f"  >>> hint {needle!r} present: …{text[max(0,idx-40):idx+80]}…")
                    break
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
